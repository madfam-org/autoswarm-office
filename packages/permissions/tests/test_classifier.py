"""Tests for the ActionClassifier tool-name-to-category mapping."""

from __future__ import annotations

import pytest

from autoswarm_permissions.classifier import ActionClassifier
from autoswarm_permissions.engine import PermissionEngine
from autoswarm_permissions.types import ActionCategory, PermissionLevel


@pytest.fixture()
def classifier() -> ActionClassifier:
    """Return a fresh ActionClassifier instance."""
    return ActionClassifier()


class TestClassifyBash:
    """Tool names related to shell execution should classify as BASH_EXECUTE."""

    def test_classify_bash(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("bash") == ActionCategory.BASH_EXECUTE

    def test_classify_shell(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("shell") == ActionCategory.BASH_EXECUTE

    def test_classify_terminal(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("terminal") == ActionCategory.BASH_EXECUTE

    def test_classify_exec(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("exec") == ActionCategory.BASH_EXECUTE


class TestClassifyGitPush:
    """Git push related tool names should classify as GIT_PUSH."""

    def test_classify_git_push_exact(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("git_push") == ActionCategory.GIT_PUSH

    def test_classify_push_substring_fallback(self, classifier: ActionClassifier) -> None:
        """An unknown tool containing 'push' should fall back to GIT_PUSH."""
        assert classifier.classify("force_push") == ActionCategory.GIT_PUSH


class TestClassifyEmail:
    """Email-related tool names should classify as EMAIL_SEND."""

    def test_classify_send_email(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("send_email") == ActionCategory.EMAIL_SEND

    def test_classify_email(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("email") == ActionCategory.EMAIL_SEND

    def test_classify_email_substring_fallback(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("internal_email_service") == ActionCategory.EMAIL_SEND


class TestClassifyUnknownDefaults:
    """Unrecognised tool names should fall back to API_CALL."""

    def test_classify_completely_unknown(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("unknown_tool") == ActionCategory.API_CALL

    def test_classify_random_string(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("xyzzy_widget") == ActionCategory.API_CALL

    def test_classify_empty_string(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("") == ActionCategory.API_CALL


class TestClassifyCaseSensitivity:
    """The classifier normalises tool names to lowercase."""

    def test_uppercase_bash(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("BASH") == ActionCategory.BASH_EXECUTE

    def test_mixed_case_git_push(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("Git_Push") == ActionCategory.GIT_PUSH

    def test_whitespace_is_stripped(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("  bash  ") == ActionCategory.BASH_EXECUTE


class TestClassifyFileOperations:
    """File read/write tool names."""

    def test_classify_read_file(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("read_file") == ActionCategory.FILE_READ

    def test_classify_write_file(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("write_file") == ActionCategory.FILE_WRITE

    def test_classify_edit(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("edit") == ActionCategory.FILE_WRITE

    def test_classify_cat(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("cat") == ActionCategory.FILE_READ


class TestClassifyCRM:
    """CRM tool names."""

    def test_classify_crm_update(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("crm_update") == ActionCategory.CRM_UPDATE

    def test_classify_salesforce(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("salesforce") == ActionCategory.CRM_UPDATE

    def test_classify_hubspot(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("hubspot") == ActionCategory.CRM_UPDATE


class TestClassifyDeploy:
    """Deployment tool names."""

    def test_classify_deploy(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("deploy") == ActionCategory.DEPLOY

    def test_classify_kubectl(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("kubectl") == ActionCategory.DEPLOY

    def test_classify_terraform(self, classifier: ActionClassifier) -> None:
        assert classifier.classify("terraform") == ActionCategory.DEPLOY


class TestClassifyAndEvaluate:
    """Full flow: classify a tool name then evaluate its permission."""

    def test_full_flow_with_default_engine(self, classifier: ActionClassifier) -> None:
        result = classifier.classify_and_evaluate("bash")
        assert result.action_category == ActionCategory.BASH_EXECUTE
        assert result.level == PermissionLevel.ASK
        assert result.requires_approval is True

    def test_full_flow_file_read_allowed(self, classifier: ActionClassifier) -> None:
        result = classifier.classify_and_evaluate("read_file")
        assert result.action_category == ActionCategory.FILE_READ
        assert result.level == PermissionLevel.ALLOW
        assert result.requires_approval is False

    def test_full_flow_with_custom_engine(self, classifier: ActionClassifier) -> None:
        """A custom PermissionEngine with overrides should be honoured."""
        engine = PermissionEngine(
            overrides={ActionCategory.BASH_EXECUTE: PermissionLevel.ALLOW}
        )
        result = classifier.classify_and_evaluate("bash", engine=engine)
        assert result.action_category == ActionCategory.BASH_EXECUTE
        assert result.level == PermissionLevel.ALLOW
        assert result.requires_approval is False

    def test_full_flow_unknown_tool_defaults_to_api_call(
        self, classifier: ActionClassifier
    ) -> None:
        result = classifier.classify_and_evaluate("totally_unknown")
        assert result.action_category == ActionCategory.API_CALL
        # API_CALL is ALLOW by default
        assert result.level == PermissionLevel.ALLOW

    def test_full_flow_deploy_requires_approval(
        self, classifier: ActionClassifier
    ) -> None:
        result = classifier.classify_and_evaluate("deploy")
        assert result.action_category == ActionCategory.DEPLOY
        assert result.level == PermissionLevel.ASK
        assert result.requires_approval is True
