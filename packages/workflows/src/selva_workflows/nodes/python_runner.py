"""Python runner node handler — sandboxed Python code execution."""

from __future__ import annotations

import builtins as py_builtins
import ast
import logging
from typing import Any

from ..schema import NodeDefinition
from ..safe_eval import UnsafeExpressionError, _validate_expression

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

_RESERVED_ASSIGNMENT_NAMES = {"state", "workflow_variables"}


def _safe_builtins() -> dict[str, Any]:
    return {name: getattr(py_builtins, name) for name in _SAFE_BUILTINS if hasattr(py_builtins, name)}


def _collect_declared_names(node: ast.AST) -> set[str]:
    """Collect names assigned by supported statement forms."""
    names: set[str] = set()

    def collect_stmt(stmt: ast.stmt) -> None:
        if isinstance(stmt, ast.If):
            for child in stmt.body:
                collect_stmt(child)
            for child in stmt.orelse:
                collect_stmt(child)
            return

        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if not isinstance(target, ast.Name):
                    raise UnsafeExpressionError("assignment target must be plain variable names")
                names.add(target.id)
            return

        if isinstance(stmt, ast.AnnAssign):
            if not isinstance(stmt.target, ast.Name):
                raise UnsafeExpressionError("annotated assignment target must be variable name")
            names.add(stmt.target.id)
            return

        if isinstance(stmt, ast.AugAssign):
            if not isinstance(stmt.target, ast.Name):
                raise UnsafeExpressionError("augmented assignment target must be variable name")
            names.add(stmt.target.id)

    for stmt in node.body:
        collect_stmt(stmt)
    return names


def _validate_python_script(tree: ast.AST, *, allowed_names: set[str]) -> None:
    """Validate a python script against a restricted statement/expr grammar."""

    def _validate_expr(expr_node: ast.AST) -> None:
        _validate_expression(
            expr_node,
            allowed_names=allowed_names,
            allowed_call_targets={
                "len",
                "str",
                "int",
                "float",
                "sorted",
                "sum",
                "min",
                "max",
                "bool",
            },
            allowed_get_attrs_for={"state", "result"},
        )

    def _validate_stmt(node: ast.stmt) -> None:
        if isinstance(node, ast.Expr):
            _validate_expr(node.value)
            return

        if isinstance(node, ast.If):
            _validate_expr(node.test)
            for child in node.body:
                _validate_stmt(child)
            for child in node.orelse:
                _validate_stmt(child)
            return

        if isinstance(node, ast.Pass):
            return

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if target.id in _RESERVED_ASSIGNMENT_NAMES:
                    raise UnsafeExpressionError(
                        f"reserved variable '{target.id}' may not be reassigned"
                    )
                if not isinstance(target, ast.Name):
                    raise UnsafeExpressionError(
                        "assignment target must be plain variable names"
                    )
            _validate_expr(node.value)
            return

        if isinstance(node, ast.AnnAssign):
            if not isinstance(node.target, ast.Name):
                raise UnsafeExpressionError("annotated assignment target must be variable name")
            if node.target.id in _RESERVED_ASSIGNMENT_NAMES:
                raise UnsafeExpressionError(
                    f"reserved variable '{node.target.id}' may not be reassigned"
                )
            if node.value is not None:
                _validate_expr(node.value)
            return

        if isinstance(node, ast.AugAssign):
            if not isinstance(node.target, ast.Name):
                raise UnsafeExpressionError("augmented assignment target must be variable name")
            if node.target.id in _RESERVED_ASSIGNMENT_NAMES:
                raise UnsafeExpressionError(
                    f"reserved variable '{node.target.id}' may not be reassigned"
                )
            _validate_expr(node.value)
            return

        raise UnsafeExpressionError(
            f"statement '{node.__class__.__name__}' is not allowed"
        )

    if not isinstance(tree, ast.Module):
        raise UnsafeExpressionError("script must be a module")
    # Hard cap on body length to limit runaway script abuse.
    if len(tree.body) > 256:
        raise UnsafeExpressionError("script has too many statements")

    for statement in tree.body:
        if not isinstance(statement, ast.stmt):
            raise UnsafeExpressionError("non-statement node in module body")
        _validate_stmt(statement)


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
            tree = ast.parse(code, mode="exec")
            safe_builtins = _safe_builtins()
            workflow_variables = state.get("workflow_variables", {})
            declared_names = _collect_declared_names(tree=tree)
            allowed_names = {
                "state",
                "result",
                "workflow_variables",
                *workflow_variables.keys(),
                *safe_builtins.keys(),
                *declared_names,
            }
            sandbox_globals: dict[str, Any] = {
                "__builtins__": safe_builtins,
                "state": dict(state),
                "result": None,
            }

            # Inject workflow variables for convenience
            for key, value in workflow_variables.items():
                sandbox_globals[key] = value

            try:
                _validate_python_script(tree, allowed_names=allowed_names)
                exec(compile(tree, "<python_runner>", mode="exec"), sandbox_globals)  # noqa: S102
            except UnsafeExpressionError as exc:
                logger.error("Python runner node '%s' blocked unsafe code: %s", node.id, exc)
                return {
                    **state,
                    "status": "error",
                    "result": {"error": f"Python execution blocked: {exc}"},
                    "current_node_id": node.id,
                }
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
            workflow_vars = dict(workflow_variables)
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
