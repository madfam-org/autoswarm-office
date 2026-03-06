"""Compute token budget manager for rate-limiting swarm operations."""

from __future__ import annotations

from datetime import datetime, timezone


class ComputeTokenManager:
    """Tracks a daily compute-token budget for swarm operations.

    Every dispatchable action has a token cost.  The manager enforces
    the daily limit and provides introspection into remaining capacity.
    """

    COST_TABLE: dict[str, int] = {
        "draft_agent": 50,
        "dispatch_task": 10,
        "bash_execute": 5,
        "git_push": 20,
        "email_send": 15,
        "api_call": 3,
    }

    def __init__(self, daily_limit: int = 1000) -> None:
        if daily_limit <= 0:
            raise ValueError("daily_limit must be a positive integer")
        self.daily_limit = daily_limit
        self.used: int = 0
        self.reset_at: datetime = self._next_midnight_utc()

    @staticmethod
    def _next_midnight_utc() -> datetime:
        now = datetime.now(timezone.utc)
        return now.replace(hour=0, minute=0, second=0, microsecond=0).replace(
            day=now.day + 1
        )

    @property
    def remaining(self) -> int:
        return self.daily_limit - self.used

    def _cost_for(self, action: str, count: int) -> int:
        if action not in self.COST_TABLE:
            raise KeyError(
                f"Unknown action '{action}'. "
                f"Valid actions: {', '.join(sorted(self.COST_TABLE))}"
            )
        if count < 1:
            raise ValueError("count must be at least 1")
        return self.COST_TABLE[action] * count

    def can_afford(self, action: str, count: int = 1) -> bool:
        """Check whether the budget can cover *count* instances of *action*."""
        return self._cost_for(action, count) <= self.remaining

    def deduct(self, action: str, count: int = 1) -> int:
        """Deduct token cost for *count* instances of *action*.

        Returns:
            Remaining token budget after deduction.

        Raises:
            ValueError: If the remaining budget is insufficient.
        """
        cost = self._cost_for(action, count)
        if cost > self.remaining:
            raise ValueError(
                f"Insufficient compute tokens: need {cost}, have {self.remaining}"
            )
        self.used += cost
        return self.remaining

    def get_status(self) -> dict:
        """Snapshot of the current token budget state."""
        return {
            "daily_limit": self.daily_limit,
            "used": self.used,
            "remaining": self.remaining,
            "reset_at": self.reset_at.isoformat(),
        }

    def reset(self) -> None:
        """Reset usage counter and schedule next reset at midnight UTC."""
        self.used = 0
        self.reset_at = self._next_midnight_utc()
