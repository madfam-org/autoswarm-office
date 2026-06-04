"""Tests for workflow-safe expression evaluation helpers."""

from __future__ import annotations

import pytest

from selva_workflows.safe_eval import UnsafeExpressionError, safe_eval_bool_expression


def test_safe_eval_bool_expression_evaluates_expected_context() -> None:
    value = safe_eval_bool_expression(
        "variables.get('score', 0) > 0.5 and status == 'running'",
        {
            "variables": {"score": 0.7},
            "status": "running",
            "len": len,
        },
        allowed_call_targets={"len"},
        allowed_get_attrs_for={"variables"},
    )
    assert value is True


def test_safe_eval_bool_expression_rejects_attribute_access() -> None:
    with pytest.raises(UnsafeExpressionError, match="attribute access is not allowed"):
        safe_eval_bool_expression(
            "state.__dict__",
            {"state": {}},
            allowed_get_attrs_for={"state"},
        )


def test_safe_eval_bool_expression_empty_expression() -> None:
    with pytest.raises(UnsafeExpressionError, match="empty expression"):
        safe_eval_bool_expression("   ", {})

