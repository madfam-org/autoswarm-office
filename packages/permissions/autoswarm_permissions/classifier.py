"""Tool-name-to-action-category classifier for the HITL permission system."""

from __future__ import annotations

from .engine import PermissionEngine
from .types import ActionCategory, PermissionResult


class ActionClassifier:
    """Maps tool invocation names to permission action categories.

    The classifier first checks an explicit lookup table, then falls
    back to substring matching heuristics, and finally defaults to
    ``API_CALL`` for unrecognised tools.
    """

    TOOL_CATEGORY_MAP: dict[str, ActionCategory] = {
        # Shell / execution
        "bash": ActionCategory.BASH_EXECUTE,
        "shell": ActionCategory.BASH_EXECUTE,
        "terminal": ActionCategory.BASH_EXECUTE,
        "exec": ActionCategory.BASH_EXECUTE,
        # File read
        "read_file": ActionCategory.FILE_READ,
        "cat": ActionCategory.FILE_READ,
        "head": ActionCategory.FILE_READ,
        "tail": ActionCategory.FILE_READ,
        "less": ActionCategory.FILE_READ,
        # File write
        "write_file": ActionCategory.FILE_WRITE,
        "edit": ActionCategory.FILE_WRITE,
        "create_file": ActionCategory.FILE_WRITE,
        "patch": ActionCategory.FILE_WRITE,
        # Git
        "git_commit": ActionCategory.GIT_COMMIT,
        "git_push": ActionCategory.GIT_PUSH,
        # Email
        "send_email": ActionCategory.EMAIL_SEND,
        "email": ActionCategory.EMAIL_SEND,
        # CRM
        "crm_update": ActionCategory.CRM_UPDATE,
        "salesforce": ActionCategory.CRM_UPDATE,
        "hubspot": ActionCategory.CRM_UPDATE,
        # Deploy
        "deploy": ActionCategory.DEPLOY,
        "kubectl": ActionCategory.DEPLOY,
        "terraform": ActionCategory.DEPLOY,
        # API / HTTP
        "http_request": ActionCategory.API_CALL,
        "fetch": ActionCategory.API_CALL,
        "curl": ActionCategory.API_CALL,
    }

    # Ordered list of (substring, category) for fallback heuristics.
    # Order matters: more specific substrings should come first.
    _FALLBACK_RULES: list[tuple[str, ActionCategory]] = [
        ("push", ActionCategory.GIT_PUSH),
        ("commit", ActionCategory.GIT_COMMIT),
        ("deploy", ActionCategory.DEPLOY),
        ("write", ActionCategory.FILE_WRITE),
        ("create", ActionCategory.FILE_WRITE),
        ("edit", ActionCategory.FILE_WRITE),
        ("read", ActionCategory.FILE_READ),
        ("email", ActionCategory.EMAIL_SEND),
        ("mail", ActionCategory.EMAIL_SEND),
        ("crm", ActionCategory.CRM_UPDATE),
        ("bash", ActionCategory.BASH_EXECUTE),
        ("shell", ActionCategory.BASH_EXECUTE),
        ("exec", ActionCategory.BASH_EXECUTE),
    ]

    def classify(
        self,
        tool_name: str,
        params: dict | None = None,
    ) -> ActionCategory:
        """Classify a tool invocation into an action category.

        Args:
            tool_name: The name of the tool being invoked.
            params: Optional parameters (reserved for future context-aware
                    classification, e.g. distinguishing ``git status`` from
                    ``git push``).

        Returns:
            The ``ActionCategory`` matching the tool.
        """
        normalised = tool_name.strip().lower()

        # Exact match
        if normalised in self.TOOL_CATEGORY_MAP:
            return self.TOOL_CATEGORY_MAP[normalised]

        # Substring heuristics
        for substring, category in self._FALLBACK_RULES:
            if substring in normalised:
                return category

        return ActionCategory.API_CALL

    def classify_and_evaluate(
        self,
        tool_name: str,
        params: dict | None = None,
        engine: PermissionEngine | None = None,
    ) -> PermissionResult:
        """Classify a tool invocation and immediately evaluate its permission.

        Convenience method combining classification with engine evaluation.

        Args:
            tool_name: The name of the tool being invoked.
            params: Optional tool parameters.
            engine: A ``PermissionEngine`` instance. If ``None`` a default
                    engine is constructed.

        Returns:
            A ``PermissionResult`` for the classified action.
        """
        category = self.classify(tool_name, params)
        permission_engine = engine or PermissionEngine()
        return permission_engine.evaluate(category)
