"""Tests for the shared safe expression evaluator in selva_tools."""

from __future__ import annotations

import pytest

from selva_tools.safe_eval import UnsafeExpressionError, safe_eval_expression


def test_safe_eval_expression_supports_allowed_context() -> None:
    expr = "len(message) == 5 and vars_.get('score', 0) >= 10"
    value = safe_eval_expression(
        expr,
        {
            "len": len,
            "message": "hello",
            "vars_": {"score": 12},
        },
        allowed_call_targets={"len"},
        allowed_get_attrs_for={"vars_"},
    )
    assert value is True


def test_safe_eval_unknown_name_is_blocked() -> None:
    with pytest.raises(UnsafeExpressionError, match="unknown name 'missing'"):
        safe_eval_expression("missing > 0", {"x": 1}, allowed_get_attrs_for=set())


def test_safe_eval_disallows_comprehension() -> None:
    with pytest.raises(UnsafeExpressionError, match="comprehensions and f-strings are not allowed"):
        safe_eval_expression(
            "[x for x in [1, 2, 3]]",
            {"x": 1},
            allowed_call_targets=set(),
            allowed_get_attrs_for=set(),
        )

