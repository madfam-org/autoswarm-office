"""Tests for the ComputeTokenManager budget system."""

from __future__ import annotations

import pytest

from packages.orchestrator.src.compute_tokens import ComputeTokenManager


@pytest.fixture()
def manager() -> ComputeTokenManager:
    """Return a ComputeTokenManager with the default 1000-token daily limit."""
    return ComputeTokenManager(daily_limit=1000)


@pytest.fixture()
def small_budget() -> ComputeTokenManager:
    """Return a manager with a small 100-token budget for edge-case testing."""
    return ComputeTokenManager(daily_limit=100)


class TestComputeTokenManagerInitialState:
    """Verify the manager initialises with correct defaults."""

    def test_daily_limit_matches_constructor(self, manager: ComputeTokenManager) -> None:
        assert manager.daily_limit == 1000

    def test_used_starts_at_zero(self, manager: ComputeTokenManager) -> None:
        assert manager.used == 0

    def test_remaining_equals_daily_limit_at_start(
        self, manager: ComputeTokenManager
    ) -> None:
        assert manager.remaining == 1000

    def test_custom_daily_limit(self) -> None:
        m = ComputeTokenManager(daily_limit=500)
        assert m.daily_limit == 500
        assert m.remaining == 500

    def test_invalid_daily_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="daily_limit must be a positive integer"):
            ComputeTokenManager(daily_limit=0)

    def test_negative_daily_limit_raises(self) -> None:
        with pytest.raises(ValueError, match="daily_limit must be a positive integer"):
            ComputeTokenManager(daily_limit=-10)

    def test_get_status_initial(self, manager: ComputeTokenManager) -> None:
        status = manager.get_status()
        assert status["daily_limit"] == 1000
        assert status["used"] == 0
        assert status["remaining"] == 1000
        assert "reset_at" in status


class TestDeduct:
    """Verify token deduction works correctly."""

    def test_deduct_single_action(self, manager: ComputeTokenManager) -> None:
        remaining = manager.deduct("draft_agent")
        assert manager.used == 50
        assert remaining == 950

    def test_deduct_multiple_count(self, manager: ComputeTokenManager) -> None:
        remaining = manager.deduct("dispatch_task", count=3)
        expected_cost = 10 * 3
        assert manager.used == expected_cost
        assert remaining == 1000 - expected_cost

    def test_deduct_updates_remaining(self, manager: ComputeTokenManager) -> None:
        manager.deduct("bash_execute")  # cost 5
        manager.deduct("git_push")  # cost 20
        assert manager.used == 25
        assert manager.remaining == 975

    def test_deduct_returns_remaining(self, manager: ComputeTokenManager) -> None:
        result = manager.deduct("api_call")  # cost 3
        assert result == 997

    def test_deduct_unknown_action_raises(self, manager: ComputeTokenManager) -> None:
        with pytest.raises(KeyError, match="Unknown action 'nonexistent'"):
            manager.deduct("nonexistent")

    def test_deduct_zero_count_raises(self, manager: ComputeTokenManager) -> None:
        with pytest.raises(ValueError, match="count must be at least 1"):
            manager.deduct("api_call", count=0)

    def test_deduct_negative_count_raises(self, manager: ComputeTokenManager) -> None:
        with pytest.raises(ValueError, match="count must be at least 1"):
            manager.deduct("api_call", count=-1)


class TestCanAfford:
    """Verify budget affordability checks."""

    def test_can_afford_when_budget_sufficient(
        self, manager: ComputeTokenManager
    ) -> None:
        assert manager.can_afford("draft_agent") is True

    def test_can_afford_when_budget_insufficient(self) -> None:
        m = ComputeTokenManager(daily_limit=10)
        # draft_agent costs 50 -- exceeds the 10-token limit
        assert m.can_afford("draft_agent") is False

    def test_can_afford_exact_remaining(self, small_budget: ComputeTokenManager) -> None:
        """Budget of 100 can exactly afford 2 draft_agents (50 each)."""
        assert small_budget.can_afford("draft_agent", count=2) is True

    def test_cannot_afford_one_over_limit(
        self, small_budget: ComputeTokenManager
    ) -> None:
        """Budget of 100 cannot afford 3 draft_agents (150 > 100)."""
        assert small_budget.can_afford("draft_agent", count=3) is False

    def test_can_afford_after_deduction(
        self, small_budget: ComputeTokenManager
    ) -> None:
        small_budget.deduct("draft_agent")  # 50 used, 50 remaining
        assert small_budget.can_afford("draft_agent") is True
        assert small_budget.can_afford("draft_agent", count=2) is False


class TestInsufficientTokensRaises:
    """Verify ValueError when attempting to overdraft."""

    def test_overdraft_raises_value_error(self) -> None:
        m = ComputeTokenManager(daily_limit=10)
        with pytest.raises(ValueError, match="Insufficient compute tokens"):
            m.deduct("draft_agent")  # costs 50, only 10 available

    def test_overdraft_after_partial_use(
        self, small_budget: ComputeTokenManager
    ) -> None:
        small_budget.deduct("draft_agent")  # 50 used, 50 remaining
        small_budget.deduct("draft_agent")  # 100 used, 0 remaining
        with pytest.raises(ValueError, match="Insufficient compute tokens"):
            small_budget.deduct("api_call")  # costs 3, 0 remaining

    def test_overdraft_preserves_state(
        self, small_budget: ComputeTokenManager
    ) -> None:
        """Failed deduction should not mutate the used counter."""
        small_budget.deduct("draft_agent")  # 50 used
        used_before = small_budget.used
        with pytest.raises(ValueError):
            small_budget.deduct("draft_agent", count=2)  # 100 > 50 remaining
        assert small_budget.used == used_before


class TestReset:
    """Verify budget reset behaviour."""

    def test_reset_clears_used(self, manager: ComputeTokenManager) -> None:
        manager.deduct("draft_agent")
        assert manager.used > 0
        manager.reset()
        assert manager.used == 0

    def test_reset_restores_remaining(self, manager: ComputeTokenManager) -> None:
        manager.deduct("draft_agent")
        manager.reset()
        assert manager.remaining == manager.daily_limit

    def test_reset_updates_reset_at(self, manager: ComputeTokenManager) -> None:
        original_reset_at = manager.reset_at
        manager.reset()
        # reset_at is recalculated; the new value may be different if the
        # clock ticked across midnight, but it should always be set.
        assert manager.reset_at is not None
        assert hasattr(manager.reset_at, "isoformat")

    def test_double_reset_is_idempotent(self, manager: ComputeTokenManager) -> None:
        manager.reset()
        manager.reset()
        assert manager.used == 0
        assert manager.remaining == manager.daily_limit
