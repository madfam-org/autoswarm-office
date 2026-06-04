"""Safe expression evaluation helper used by workflow runtime conditions."""

from __future__ import annotations

import ast
from typing import Any, Mapping


class UnsafeExpressionError(ValueError):
    """Raised when an expression uses unsupported AST nodes."""


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


def _validate_expression(
    node: ast.AST,
    allowed_names: set[str],
    allowed_call_targets: set[str],
    allowed_get_attrs_for: set[str],
) -> None:
    if isinstance(node, ast.Expression):
        _validate_expression(
            node.body,
            allowed_names=allowed_names,
            allowed_call_targets=allowed_call_targets,
            allowed_get_attrs_for=allowed_get_attrs_for,
        )
        return

    if isinstance(node, ast.Name):
        if node.id not in allowed_names:
            raise UnsafeExpressionError(f"unknown name: {node.id}")
        return

    if isinstance(node, ast.Constant):
        return

    if isinstance(node, ast.List | ast.Tuple | ast.Set):
        for child in node.elts:
            _validate_expression(child, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        return

    if isinstance(node, ast.Dict):
        for key in node.keys:
            if key is not None:
                _validate_expression(key, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        for value in node.values:
            _validate_expression(value, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        return

    if isinstance(node, ast.BoolOp):
        if not isinstance(node.op, _ALLOWED_BOOLOPS):
            raise UnsafeExpressionError("unsupported bool operator")
        for value in node.values:
            _validate_expression(value, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        return

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise UnsafeExpressionError("unsupported arithmetic operator")
        _validate_expression(node.left, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        _validate_expression(node.right, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        return

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise UnsafeExpressionError("unsupported unary operator")
        _validate_expression(node.operand, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        return

    if isinstance(node, ast.IfExp):
        _validate_expression(node.test, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        _validate_expression(node.body, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        _validate_expression(node.orelse, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        return

    if isinstance(node, ast.Compare):
        _validate_expression(node.left, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            if not isinstance(op, _ALLOWED_CMP_OPS):
                raise UnsafeExpressionError("unsupported comparison operator")
            _validate_expression(
                comparator,
                allowed_names=allowed_names,
                allowed_call_targets=allowed_call_targets,
                allowed_get_attrs_for=allowed_get_attrs_for,
            )
        return

    if isinstance(node, ast.Subscript):
        _validate_expression(node.value, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        _validate_expression(node.slice, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        return

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name):
            if node.func.id not in allowed_call_targets:
                raise UnsafeExpressionError(f"call to '{node.func.id}' is not allowed")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr != "get":
                raise UnsafeExpressionError("only .get() is allowed for attribute calls")
            if not isinstance(node.func.value, ast.Name) or node.func.value.id not in allowed_get_attrs_for:
                raise UnsafeExpressionError(".get() is allowed only on approved dict-like inputs")
            _validate_expression(node.func.value, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        else:
            raise UnsafeExpressionError("unsupported call syntax")

        for arg in node.args:
            _validate_expression(arg, allowed_names, allowed_call_targets, allowed_get_attrs_for)
        for keyword in node.keywords:
            if keyword.value is not None:
                _validate_expression(
                    keyword.value,
                    allowed_names=allowed_names,
                    allowed_call_targets=allowed_call_targets,
                    allowed_get_attrs_for=allowed_get_attrs_for,
                )
        return

    if isinstance(node, ast.Attribute):
        # Attribute reads are not permitted except through explicit .get call.
        raise UnsafeExpressionError("attribute access is not allowed")

    if isinstance(node, ast.Lambda):
        raise UnsafeExpressionError("lambda expressions are not allowed")

    if isinstance(
        node,
        (
            ast.ListComp,
            ast.SetComp,
            ast.DictComp,
            ast.GeneratorExp,
            ast.FormattedValue,
            ast.JoinedStr,
        ),
    ):
        raise UnsafeExpressionError("comprehensions and f-strings are not allowed")

    # Unknown statement/expr node in eval mode.
    raise UnsafeExpressionError(f"expression node {node.__class__.__name__} is not allowed")


def safe_eval_bool_expression(
    expression: str,
    context: Mapping[str, Any],
    *,
    allowed_call_targets: set[str] | None = None,
    allowed_get_attrs_for: set[str] | None = None,
) -> bool:
    """Evaluate a restricted expression to bool."""
    if not expression.strip():
        raise UnsafeExpressionError("empty expression")

    allowed_call_targets = allowed_call_targets or set(context)
    allowed_get_attrs_for = allowed_get_attrs_for or set(context)

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"invalid expression: {exc.msg}") from exc

    _validate_expression(
        tree,
        set(context),
        set(allowed_call_targets),
        set(allowed_get_attrs_for),
    )

    code = compile(tree, "<safe-expression>", mode="eval")
    return bool(eval(code, {"__builtins__": {}}, dict(context)))

