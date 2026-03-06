"""Tests for the PermissionEngine evaluation logic."""

from __future__ import annotations

import pytest

from autoswarm_permissions.engine import PermissionEngine
from autoswarm_permissions.matrix import DEFAULT_PERMISSION_MATRIX
from autoswarm_permissions.types import ActionCategory, PermissionLevel, PermissionResult


@pytest.fixture()
def engine() -> PermissionEngine:
    """Return a PermissionEngine using the default permission matrix."""
    return PermissionEngine()


class TestAllowPermission:
    """FILE_READ is ALLOW by default in the matrix."""

    def test_file_read_is_allowed(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.FILE_READ)
        assert result.level == PermissionLevel.ALLOW

    def test_file_read_does_not_require_approval(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.FILE_READ)
        assert result.requires_approval is False

    def test_file_read_result_type(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.FILE_READ)
        assert isinstance(result, PermissionResult)

    def test_file_read_reason_contains_category(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.FILE_READ)
        assert "file_read" in result.reason

    def test_api_call_is_also_allowed(self, engine: PermissionEngine) -> None:
        """API_CALL is ALLOW by default in the matrix."""
        result = engine.evaluate(ActionCategory.API_CALL)
        assert result.level == PermissionLevel.ALLOW
        assert result.requires_approval is False


class TestAskPermission:
    """FILE_WRITE, BASH_EXECUTE, GIT_PUSH etc. are ASK by default."""

    def test_file_write_requires_approval(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.FILE_WRITE)
        assert result.level == PermissionLevel.ASK
        assert result.requires_approval is True

    def test_bash_execute_requires_approval(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.BASH_EXECUTE)
        assert result.level == PermissionLevel.ASK
        assert result.requires_approval is True

    def test_git_push_requires_approval(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.GIT_PUSH)
        assert result.level == PermissionLevel.ASK
        assert result.requires_approval is True

    def test_deploy_requires_approval(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.DEPLOY)
        assert result.level == PermissionLevel.ASK
        assert result.requires_approval is True

    def test_ask_reason_mentions_approval(self, engine: PermissionEngine) -> None:
        result = engine.evaluate(ActionCategory.FILE_WRITE)
        assert "requires human approval" in result.reason


class TestDenyPermission:
    """Test DENY level behaviour via override."""

    def test_deny_override_blocks_action(self) -> None:
        engine = PermissionEngine(
            overrides={ActionCategory.FILE_READ: PermissionLevel.DENY}
        )
        result = engine.evaluate(ActionCategory.FILE_READ)
        assert result.level == PermissionLevel.DENY
        assert result.requires_approval is False

    def test_deny_reason_mentions_denied(self) -> None:
        engine = PermissionEngine(
            overrides={ActionCategory.BASH_EXECUTE: PermissionLevel.DENY}
        )
        result = engine.evaluate(ActionCategory.BASH_EXECUTE)
        assert "denied" in result.reason.lower()

    def test_deny_via_update_permission(self, engine: PermissionEngine) -> None:
        engine.update_permission(ActionCategory.GIT_PUSH, PermissionLevel.DENY)
        result = engine.evaluate(ActionCategory.GIT_PUSH)
        assert result.level == PermissionLevel.DENY


class TestShouldInterrupt:
    """Test the should_interrupt convenience method."""

    def test_should_interrupt_true_for_ask(self, engine: PermissionEngine) -> None:
        assert engine.should_interrupt(ActionCategory.FILE_WRITE) is True

    def test_should_interrupt_false_for_allow(self, engine: PermissionEngine) -> None:
        assert engine.should_interrupt(ActionCategory.FILE_READ) is False

    def test_should_interrupt_false_for_deny(self) -> None:
        engine = PermissionEngine(
            overrides={ActionCategory.DEPLOY: PermissionLevel.DENY}
        )
        assert engine.should_interrupt(ActionCategory.DEPLOY) is False

    def test_should_interrupt_reflects_update(self, engine: PermissionEngine) -> None:
        # Initially ASK
        assert engine.should_interrupt(ActionCategory.GIT_PUSH) is True
        # Change to ALLOW
        engine.update_permission(ActionCategory.GIT_PUSH, PermissionLevel.ALLOW)
        assert engine.should_interrupt(ActionCategory.GIT_PUSH) is False


class TestCustomOverrides:
    """Verify that constructor overrides take effect."""

    def test_override_allow_to_deny(self) -> None:
        engine = PermissionEngine(
            overrides={ActionCategory.API_CALL: PermissionLevel.DENY}
        )
        result = engine.evaluate(ActionCategory.API_CALL)
        assert result.level == PermissionLevel.DENY

    def test_override_ask_to_allow(self) -> None:
        engine = PermissionEngine(
            overrides={ActionCategory.FILE_WRITE: PermissionLevel.ALLOW}
        )
        result = engine.evaluate(ActionCategory.FILE_WRITE)
        assert result.level == PermissionLevel.ALLOW
        assert result.requires_approval is False

    def test_multiple_overrides(self) -> None:
        engine = PermissionEngine(
            overrides={
                ActionCategory.FILE_WRITE: PermissionLevel.ALLOW,
                ActionCategory.DEPLOY: PermissionLevel.DENY,
                ActionCategory.EMAIL_SEND: PermissionLevel.ALLOW,
            }
        )
        assert engine.evaluate(ActionCategory.FILE_WRITE).level == PermissionLevel.ALLOW
        assert engine.evaluate(ActionCategory.DEPLOY).level == PermissionLevel.DENY
        assert engine.evaluate(ActionCategory.EMAIL_SEND).level == PermissionLevel.ALLOW

    def test_overrides_dont_affect_unrelated_categories(self) -> None:
        engine = PermissionEngine(
            overrides={ActionCategory.DEPLOY: PermissionLevel.DENY}
        )
        # FILE_READ should still be ALLOW (default)
        assert engine.evaluate(ActionCategory.FILE_READ).level == PermissionLevel.ALLOW

    def test_custom_full_matrix(self) -> None:
        """Supplying a complete custom matrix replaces the default entirely."""
        custom_matrix = {
            ActionCategory.FILE_READ: PermissionLevel.DENY,
            ActionCategory.FILE_WRITE: PermissionLevel.DENY,
        }
        engine = PermissionEngine(matrix=custom_matrix)
        assert engine.evaluate(ActionCategory.FILE_READ).level == PermissionLevel.DENY
        assert engine.evaluate(ActionCategory.FILE_WRITE).level == PermissionLevel.DENY
        # Categories not in the custom matrix default to ASK
        assert engine.evaluate(ActionCategory.GIT_PUSH).level == PermissionLevel.ASK
