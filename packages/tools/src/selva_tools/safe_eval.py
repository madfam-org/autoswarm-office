"""Safe expression helpers for tool input.

These helpers intentionally block dynamic execution primitives while
retaining a narrow subset of expression features used by Selva tooling.
"""

from __future__ import annotations

import ast
from typing import Any, Mapping


class UnsafeExpressionError(ValueError):
    """Raised when an expression uses a disallowed AST node or name."""


_ALLOWED_BINOPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.MatMult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
)

_ALLOWED_BOOLOPS = (ast.And, ast.Or)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub, ast.Not)
_ALLOWED_CMP_OPS = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
)


def _validate_expr_node(
    node: ast.AST,
    *,
    allowed_names: set[str],
    allowed_call_targets: set[str],
    allowed_get_attrs_for: set[str],
) -> None:
    if isinstance(node, ast.Expression):
        _validate_expr_node(node.body, allowed_names=allowed_names, allowed_call_targets=allowed_call_targets, allowed_get_attrs_for=allowed_get_attrs_for)
        return

    if isinstance(node, ast.Name):
        if node.id not in allowed_names:
            raise UnsafeExpressionError(f"unknown name '{node.id}'")
        return

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOLOPS):
            raise UnsafeExpressionError("boolean operator not allowed")
        for value in node.values:
            _validate_expr_node(
                value,
                allowed_names=allowed_names,
                allowed_call_targets=allowed_call_targets,
                allowed_get_attrs_for=allowed_get_attrs_for,
            )
        return

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise UnsafeExpressionError("arithmetic operator not allowed")
        _validate_expr_node(
            node.left,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        _validate_expr_node(
            node.right,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise UnsafeExpressionError("unary operator not allowed")
        _validate_expr_node(
            node.operand,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        return

    if isinstance(node, ast.IfExp):
        _validate_expr_node(
            node.test,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        _validate_expr_node(
            node.body,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        _validate_expr_node(
            node.orelse,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        return

    if isinstance(node, ast.Compare):
        _validate_expr_node(
            node.left,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            if not isinstance(op, _ALLOWED_CMP_OPS):
                raise UnsafeExpressionError("comparison operator not allowed")
            _validate_expr_node(
                comparator,
                allowed_names=allowed_names,
                allowed_call_targets=allowed_call_targets,
                allowed_get_attrs_for=allowed_get_attrs_for,
            )
        return

    if isinstance(node, ast.Subscript):
        _validate_expr_node(
            node.value,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        _validate_expr_node(
            node.slice,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        return

    if isinstance(node, ast.Call):
        # Keep calls deliberately narrow. Name calls map directly to names
        # in execution context. Attribute calls are only allowed for
        # dict-style .get(...) access.
        if isinstance(node.func, ast.Name):
            if node.func.id not in allowed_call_targets:
                raise UnsafeExpressionError(f"call to '{node.func.id}' is not allowed")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr != "get":
                raise UnsafeExpressionError("only .get() is allowed for attribute calls")
            if not isinstance(node.func.value, ast.Name):
                raise UnsafeExpressionError("attribute call only allowed on named variables")
            if node.func.value.id not in allowed_get_attrs_for:
                raise UnsafeExpressionError(
                    f".get() allowed only on {sorted(allowed_get_attrs_for)}"
                )
        else:
            raise UnsafeExpressionError("call expression form not allowed")

        for arg in node.args:
            _validate_expr_node(
                arg,
                allowed_names=allowed_names,
                allowed_call_targets=allowed_call_targets,
                allowed_get_attrs_for=allowed_get_attrs_for,
            )
        for kw in node.keywords:
            if kw.arg is not None:
                _validate_expr_node(
                    kw.value,
                    allowed_names=allowed_names,
                    allowed_call_targets=allowed_call_targets,
                    allowed_get_attrs_for=allowed_get_attrs_for,
                )
        return

    if isinstance(node, (ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.Slice)):
        # Nested node types are recursively validated below as needed.
        for child in ast.iter_child_nodes(node):
            _validate_expr_node(
                child,
                allowed_names=allowed_names,
                allowed_call_targets=allowed_call_targets,
                allowed_get_attrs_for=allowed_get_attrs_for,
            )
        return

    if isinstance(node, ast.Attribute):
        # Attribute reads are intentionally blocked except through the
        # explicit .get(...) call path above.
        raise UnsafeExpressionError("attribute access is not allowed")

    if isinstance(node, (ast.Lambda, ast.If)):
        raise UnsafeExpressionError("lambda / conditional statements are not allowed")

    if isinstance(
        node,
        (
            ast.Break,
            ast.Continue,
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.ClassDef,
            ast.With,
            ast.For,
            ast.While,
            ast.Global,
            ast.Nonlocal,
            ast.Raise,
            ast.Try,
            ast.Assert,
            ast.Delete,
            ast.Import,
            ast.ImportFrom,
        ),
    ):
        raise UnsafeExpressionError(f"statement '{node.__class__.__name__}' is not allowed")

    if isinstance(
        node,
        (
            ast.ListComp,
            ast.DictComp,
            ast.SetComp,
            ast.GeneratorExp,
            ast.Lambda,
        ),
    ):
        raise UnsafeExpressionError("comprehension expressions are not allowed")

    # Default deny: only explicitly handled constructs are allowed.
    raise UnsafeExpressionError(f"node type {node.__class__.__name__} is not allowed")


def safe_eval_expression(
    expression: str,
    context: Mapping[str, Any],
    *,
    allowed_call_targets: set[str] | None = None,
    allowed_get_attrs_for: set[str] | None = None,
) -> Any:
    """Evaluate a small, bounded Python expression from untrusted input."""
    if not expression.strip():
        raise UnsafeExpressionError("empty expression")

    allowed_call_targets = allowed_call_targets or set(context)
    allowed_get_attrs_for = allowed_get_attrs_for or set(context)

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"invalid expression: {exc.msg}") from exc

    allowed_names = set(context)
    _validate_expr_node(
        tree,
        allowed_names=allowed_names,
        allowed_call_targets=set(allowed_call_targets),
        allowed_get_attrs_for=set(allowed_get_attrs_for),
    )

    compiled = compile(tree, "<safe-expression>", mode="eval")
    return eval(compiled, {"__builtins__": {}}, dict(context))
