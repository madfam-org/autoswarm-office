"""YAML-to-LangGraph compiler — transforms WorkflowDefinition into a runnable graph."""

from __future__ import annotations

import logging
import os
from typing import Any

from langgraph.graph import END, StateGraph

from .context_files import ContextFileLoader  # Gap 5
from .edges import END_SENTINEL, build_conditional_router, group_edges_by_source
from .schema import (
    ContextWindowPolicy,
    NodeDefinition,
    NodeType,
    WorkflowDefinition,
)
from .validator import WorkflowValidator

logger = logging.getLogger(__name__)
_context_loader = ContextFileLoader()  # Gap 5 singleton


class CustomGraphState:
    """State schema hint for the compiled LangGraph.

    We use a plain dict at runtime but define the expected keys here for
    documentation and type-checking clarity.
    """


# State type for the compiled graph — extends BaseGraphState with workflow fields
WORKFLOW_STATE_KEYS = {
    "messages": list,
    "task_id": str,
    "agent_id": str,
    "status": str,
    "result": object,
    "requires_approval": bool,
    "approval_request_id": object,
    "agent_system_prompt": str,
    "agent_skill_ids": list,
    "workflow_variables": dict,
    "current_node_id": str,
    "description": str,
}


class WorkflowCompiler:
    """Compiles a WorkflowDefinition into a runnable LangGraph StateGraph.

    Usage:
        compiler = WorkflowCompiler()
        graph = compiler.compile(workflow_definition)
        compiled = graph.compile(checkpointer=checkpointer)
        result = compiled.invoke(initial_state)
    """

    def __init__(self, workflow_loader: Any = None, workspace_path: str | None = None) -> None:
        """Initialize the compiler.

        Args:
            workflow_loader: Optional callable(subgraph_id) -> WorkflowDefinition
                            used for resolving subgraph references.
            workspace_path: Optional path to the workspace root. If provided,
                            context files (AGENTS.md, .autoswarm.md) are loaded
                            and injected into agent node system prompts (Gap 5).
        """
        self._loader = workflow_loader
        self._workspace_path = workspace_path or os.environ.get("AUTOSWARM_WORKSPACE_PATH", "")
        self._validator = WorkflowValidator()
        self._pending_batch_nodes: list[tuple[NodeDefinition, Any]] = []

        # Gap 3: Load plugins at compile time
        self._plugin_tools: list[dict] = []
        self._plugin_context: dict[str, list[str]] = {}  # phase -> addenda
        self._load_plugins()

        # Gap 5: Load workspace context files
        self._workspace_context: str = ""
        if self._workspace_path:
            self._workspace_context = _context_loader.load_context(self._workspace_path)
            if self._workspace_context:
                logger.info(
                    "WorkflowCompiler: workspace context loaded (%d chars).",
                    len(self._workspace_context),
                )

    def _load_plugins(self) -> None:
        """Discover and load plugins (Gap 3)."""
        try:
            from selva_plugins.manager import PluginManager  # type: ignore

            plugin_dirs_str = os.environ.get("AUTOSWARM_PLUGIN_DIRS", "")
            extra_dirs = [d for d in plugin_dirs_str.split(":") if d]
            manager = PluginManager(extra_dirs=extra_dirs)
            count = manager.discover()
            if count:
                self._plugin_tools = manager.get_all_tools()
                phases = (
                    "phase_i_analyst",
                    "phase_ii_sanitizer",
                    "phase_iii_clean_swarm",
                    "phase_iv_qa_oracle",
                )
                for phase in phases:
                    self._plugin_context[phase] = manager.get_context_addenda(phase)
                logger.info(
                    "WorkflowCompiler: loaded %d plugin(s) with %d tools.",
                    count,
                    len(self._plugin_tools),
                )
        except ImportError:
            logger.debug("selva_plugins not installed — plugin discovery skipped.")
        except Exception as exc:
            logger.warning("Plugin discovery failed: %s", exc)

    def get_plugin_tools(self) -> list[dict]:
        """Return all tools contributed by loaded plugins."""
        return list(self._plugin_tools)

    def get_phase_context(self, phase: str) -> str:
        """Return the combined context string for *phase* from plugins + workspace."""
        parts: list[str] = []
        plugin_addenda = self._plugin_context.get(phase, [])
        parts.extend(plugin_addenda)
        if self._workspace_context:
            parts.append(self._workspace_context)
        return "\n\n".join(parts)

    def compile(
        self,
        workflow: WorkflowDefinition,
        *,
        validate: bool = True,
    ) -> StateGraph:
        """Compile a workflow definition into a LangGraph StateGraph.

        Args:
            workflow: The workflow to compile.
            validate: Whether to run validation first (default True).

        Returns:
            An uncompiled StateGraph. Call .compile() on it to get a runnable.

        Raises:
            ValueError: If validation fails with errors.
        """
        if validate:
            result = self._validator.validate(workflow)
            if not result.is_valid:
                error_msgs = "; ".join(e.message for e in result.errors)
                raise ValueError(f"Workflow validation failed: {error_msgs}")
            for warning in result.warnings:
                logger.warning("Workflow '%s': %s", workflow.name, warning.message)

        # Build the state graph. ``StateGraph`` is generic in StateT and
        # langgraph's stubs reject the bare ``dict`` we use as the state
        # container; the runtime accepts it fine.
        graph = StateGraph(dict)  # type: ignore[type-var]

        node_map = {n.id: n for n in workflow.nodes}
        entry_id = workflow.entry_node or workflow.nodes[0].id

        # Reset pending batch nodes for this compilation
        self._pending_batch_nodes = []

        # Build node functions (batch nodes record themselves for delegate wiring)
        built_fns: dict[str, Any] = {}
        for node_def in workflow.nodes:
            node_fn = self._build_node_function(node_def)
            built_fns[node_def.id] = node_fn

        # Wire batch node delegates now that all node functions exist
        for batch_node_def, batch_handler in self._pending_batch_nodes:
            delegate_id = batch_node_def.delegate_node_id
            if delegate_id and delegate_id in built_fns:
                batch_handler.set_delegate_fn(built_fns[delegate_id])

        # Add nodes
        for node_def in workflow.nodes:
            wrapped_fn = self._wrap_with_context_policy(built_fns[node_def.id], node_def)
            graph.add_node(node_def.id, wrapped_fn)

        # Set entry point
        graph.set_entry_point(entry_id)

        # Group edges by source and add them
        edge_groups = group_edges_by_source(workflow.edges)

        # Track which nodes have outgoing edges
        nodes_with_edges: set[str] = set()

        for source_id, edges in edge_groups.items():
            if source_id not in node_map:
                continue

            nodes_with_edges.add(source_id)

            has_conditional = any(e.condition is not None for e in edges)

            if has_conditional:
                # Use add_conditional_edges
                router = build_conditional_router(source_id, edges)
                # Collect all possible targets for the path map
                targets: set[str] = set()
                for e in edges:
                    targets.add(e.target)

                # Build path map: target -> target (identity mapping for
                # LangGraph). ``add_conditional_edges`` is typed
                # ``dict[Hashable, str]``; ``dict[str, str]`` is structurally
                # compatible but mypy needs the wider key type.
                from collections.abc import Hashable

                path_map: dict[Hashable, str] = {}
                for target in targets:
                    if target == END_SENTINEL:
                        path_map[END_SENTINEL] = END
                    else:
                        path_map[target] = target

                # Add fallback END
                if END_SENTINEL not in path_map:
                    path_map[END_SENTINEL] = END

                graph.add_conditional_edges(source_id, router, path_map)
            else:
                # Simple edges — if single target, use add_edge
                if len(edges) == 1:
                    graph.add_edge(source_id, edges[0].target)
                else:
                    # Multiple unconditional edges = fan-out (not standard in LangGraph)
                    # Use the first edge as the primary path
                    graph.add_edge(source_id, edges[0].target)
                    for extra_edge in edges[1:]:
                        logger.warning(
                            "Multiple unconditional edges from '%s'; "
                            "only first target '%s' used (extra: '%s')",
                            source_id,
                            edges[0].target,
                            extra_edge.target,
                        )

        # Nodes without outgoing edges go to END
        for node_def in workflow.nodes:
            if node_def.id not in nodes_with_edges:
                graph.add_edge(node_def.id, END)

        return graph

    def _build_node_function(self, node: NodeDefinition) -> Any:
        """Build the appropriate node handler function based on node type."""
        from .nodes.agent import AgentNodeHandler
        from .nodes.human import HumanNodeHandler
        from .nodes.literal import LiteralNodeHandler
        from .nodes.loop_counter import LoopCounterNodeHandler
        from .nodes.passthrough import PassthroughNodeHandler
        from .nodes.python_runner import PythonRunnerNodeHandler
        from .nodes.subgraph import SubgraphNodeHandler

        handlers: dict[NodeType, type] = {
            NodeType.AGENT: AgentNodeHandler,
            NodeType.HUMAN: HumanNodeHandler,
            NodeType.PASSTHROUGH: PassthroughNodeHandler,
            NodeType.PYTHON_RUNNER: PythonRunnerNodeHandler,
            NodeType.LITERAL: LiteralNodeHandler,
            NodeType.LOOP_COUNTER: LoopCounterNodeHandler,
        }

        if node.type == NodeType.SUBGRAPH:
            handler = SubgraphNodeHandler(node, workflow_loader=self._loader)
            return handler.build_node_fn()

        if node.type == NodeType.BATCH:
            return self._build_batch_node(node)

        handler_cls = handlers.get(node.type)
        if handler_cls is None:
            msg = f"Unknown node type: {node.type}"
            raise ValueError(msg)

        return handler_cls(node).build_node_fn()

    def _build_batch_node(self, node: NodeDefinition) -> Any:
        """Build a batch node, wiring up the delegate node function."""
        from .nodes.batch import BatchNodeHandler

        handler = BatchNodeHandler(node)
        # The delegate is resolved after all nodes are built (deferred).
        # Store as a placeholder — the compile() method will wire it up.
        self._pending_batch_nodes.append((node, handler))
        return handler.build_node_fn()

    def _wrap_with_context_policy(self, node_fn: Any, node: NodeDefinition) -> Any:
        """Wrap a node function with context window policy trimming."""
        policy = node.context_policy

        if policy.type == ContextWindowPolicy.KEEP_ALL:
            return node_fn

        def wrapped(state: dict) -> dict:
            # Apply context policy to messages before node execution
            trimmed = _apply_context_policy(state, policy.type, policy.n)
            return node_fn(trimmed)

        wrapped.__name__ = getattr(node_fn, "__name__", node.id)
        return wrapped


def _apply_context_policy(state: dict, policy: ContextWindowPolicy, n: int) -> dict:
    """Apply a context window policy to trim messages in state."""
    messages = state.get("messages", [])
    if not messages:
        return state

    if policy == ContextWindowPolicy.CLEAR_ALL:
        return {**state, "messages": []}
    elif policy == ContextWindowPolicy.KEEP_LAST_N:
        return {**state, "messages": messages[-n:]}
    elif policy == ContextWindowPolicy.SLIDING_WINDOW:
        # Keep first message (usually system) + last N-1
        if len(messages) <= n:
            return state
        return {**state, "messages": [messages[0]] + messages[-(n - 1) :]}

    return state
