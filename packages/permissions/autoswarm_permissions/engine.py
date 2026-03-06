"""Permission evaluation engine for the HITL system."""

from __future__ import annotations

from .matrix import DEFAULT_PERMISSION_MATRIX
from .types import ActionCategory, PermissionLevel, PermissionResult


class PermissionEngine:
    """Evaluates permission requests against a configurable matrix.

    The engine looks up the requested action category in its internal
    matrix and returns a ``PermissionResult`` indicating whether the
    action is allowed, requires approval, or is denied.
    """

    def __init__(
        self,
        matrix: dict[ActionCategory, PermissionLevel] | None = None,
        overrides: dict[ActionCategory, PermissionLevel] | None = None,
    ) -> None:
        self._matrix: dict[ActionCategory, PermissionLevel] = dict(
            matrix or DEFAULT_PERMISSION_MATRIX
        )
        if overrides:
            self._matrix.update(overrides)

    def evaluate(
        self,
        category: ActionCategory,
        context: dict | None = None,
    ) -> PermissionResult:
        """Evaluate whether an action is permitted.

        Args:
            category: The action category to evaluate.
            context: Optional contextual information (reserved for future
                     policy rules such as time-of-day or agent trust level).

        Returns:
            A ``PermissionResult`` with the decision and reasoning.
        """
        level = self._matrix.get(category, PermissionLevel.ASK)

        if level == PermissionLevel.ALLOW:
            return PermissionResult(
                action_category=category,
                level=level,
                requires_approval=False,
                reason=f"Action '{category.value}' is allowed by default policy.",
            )

        if level == PermissionLevel.DENY:
            return PermissionResult(
                action_category=category,
                level=level,
                requires_approval=False,
                reason=f"Action '{category.value}' is denied by policy.",
            )

        # ASK
        return PermissionResult(
            action_category=category,
            level=level,
            requires_approval=True,
            reason=(
                f"Action '{category.value}' requires human approval before execution."
            ),
        )

    def update_permission(
        self,
        category: ActionCategory,
        level: PermissionLevel,
    ) -> None:
        """Update the permission level for a specific action category."""
        self._matrix[category] = level

    def should_interrupt(self, category: ActionCategory) -> bool:
        """Return ``True`` if the action requires a human-in-the-loop check."""
        return self._matrix.get(category, PermissionLevel.ASK) == PermissionLevel.ASK
