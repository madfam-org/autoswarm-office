"""Python runner node handler — sandboxed Python code execution."""

from __future__ import annotations

import logging
from typing import Any

from ..schema import NodeDefinition

logger = logging.getLogger(__name__)

# Allowlisted builtins for sandboxed execution
_SAFE_BUILTINS = {
    "abs",
    "all",
    "any",
    "bool",
    "dict",
    "enumerate",
    "filter",
    "float",
    "frozenset",
    "int",
    "isinstance",
    "issubclass",
    "len",
    "list",
    "map",
    "max",
    "min",
    "print",
    "range",
    "repr",
    "reversed",
    "round",
    "set",
    "slice",
    "sorted",
    "str",
    "sum",
    "tuple",
    "type",
    "zip",
}


class PythonRunnerNodeHandler:
    """Handles execution of a 'python_runner' node.

    Runs user-provided Python code in a restricted sandbox. The code has
    access to a ``state`` dict and must set ``result`` to pass data forward.
    """

    def __init__(self, node: NodeDefinition) -> None:
        self.node = node

    def build_node_fn(self) -> Any:
        """Return a LangGraph-compatible node function."""
        node = self.node

        def python_runner_node(state: dict) -> dict:
            code = node.code or ""
            if not code.strip():
                return {**state, "current_node_id": node.id}

            # Build restricted globals
            safe_builtins = {
                k: (
                    __builtins__[k]
                    if isinstance(__builtins__, dict)
                    else getattr(__builtins__, k)
                )
                for k in _SAFE_BUILTINS
            }
            sandbox_globals: dict[str, Any] = {
                "__builtins__": safe_builtins,
                "state": dict(state),
                "result": None,
            }

            # Inject workflow variables for convenience
            for key, value in state.get("workflow_variables", {}).items():
                sandbox_globals[key] = value

            try:
                exec(code, sandbox_globals)  # noqa: S102
            except Exception as exc:
                logger.error("Python runner node '%s' failed: %s", node.id, exc)
                return {
                    **state,
                    "status": "error",
                    "result": {"error": f"Python execution error: {exc}"},
                    "current_node_id": node.id,
                }

            # Extract result and any state mutations
            run_result = sandbox_globals.get("result")
            workflow_vars = dict(state.get("workflow_variables", {}))
            if run_result is not None:
                workflow_vars[f"{node.id}_result"] = run_result

            return {
                **state,
                "workflow_variables": workflow_vars,
                "result": run_result if run_result is not None else state.get("result"),
                "current_node_id": node.id,
            }

        python_runner_node.__name__ = f"python_{node.id}"
        return python_runner_node
