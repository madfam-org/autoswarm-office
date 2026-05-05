"""Subgraph node handler — recursively compiles and invokes a nested workflow."""

from __future__ import annotations

import logging
from typing import Any

from ..schema import NodeDefinition

logger = logging.getLogger(__name__)


class SubgraphNodeHandler:
    """Handles execution of a 'subgraph' node.

    Compiles the referenced sub-workflow and invokes it inline. The subgraph
    receives the parent's state and returns its final state merged back.
    """

    def __init__(self, node: NodeDefinition, workflow_loader: Any = None) -> None:
        self.node = node
        self._loader = workflow_loader

    def build_node_fn(self) -> Any:
        """Return a LangGraph-compatible node function."""
        node = self.node
        loader = self._loader

        def subgraph_node(state: dict) -> dict:
            subgraph_id = node.subgraph_id
            if not subgraph_id:
                logger.error("Subgraph node '%s' has no subgraph_id", node.id)
                return {**state, "status": "error", "current_node_id": node.id}

            # Load the sub-workflow definition
            sub_workflow = None
            if loader is not None:
                try:
                    sub_workflow = loader(subgraph_id)
                except Exception:
                    logger.error(
                        "Failed to load subgraph '%s' for node '%s'",
                        subgraph_id,
                        node.id,
                        exc_info=True,
                    )

            if sub_workflow is None:
                logger.warning(
                    "Subgraph '%s' not found; node '%s' passing through",
                    subgraph_id,
                    node.id,
                )
                return {**state, "current_node_id": node.id}

            # Compile and invoke the sub-workflow. ``WorkflowCompiler.compile``
            # returns the uncompiled ``StateGraph``; the runnable is produced
            # by calling ``.compile()`` on that graph. The previous code
            # called ``.invoke()`` directly on the StateGraph, which raises
            # AttributeError at runtime — silently masked by the broad
            # exception handler at the call site. Surface bug fix.
            from ..compiler import WorkflowCompiler

            compiler = WorkflowCompiler(workflow_loader=loader)
            compiled_graph = compiler.compile(sub_workflow).compile()
            # langgraph stubs type ``invoke`` against ``StateT`` (the generic
            # state schema); we use a plain ``dict`` as the runtime state
            # container — see the ``StateGraph(dict)`` ignore in compiler.py.
            result = compiled_graph.invoke(state)  # type: ignore[arg-type]

            # Merge subgraph result back
            merged = {**state, **result, "current_node_id": node.id}
            return merged

        subgraph_node.__name__ = f"subgraph_{node.id}"
        return subgraph_node
