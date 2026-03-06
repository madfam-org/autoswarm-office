"""Tests for the SynergyCalculator engine."""

from __future__ import annotations

import pytest

from autoswarm_orchestrator.synergy import SynergyCalculator, SynergyRule
from autoswarm_orchestrator.types import AgentRole


@pytest.fixture()
def calculator() -> SynergyCalculator:
    """Return a SynergyCalculator with default rules."""
    return SynergyCalculator()


class TestSynergyCalculator:
    """Unit tests for SynergyCalculator.calculate and get_effective_multiplier."""

    def test_surgical_devops_synergy(self, calculator: SynergyCalculator) -> None:
        """Researcher + coder triggers the Surgical DevOps synergy at 1.3x."""
        roles = [AgentRole.RESEARCHER, AgentRole.CODER]
        active = calculator.calculate(roles)

        synergy_names = [name for name, _ in active]
        assert "Surgical DevOps" in synergy_names

        multiplier = dict(active)["Surgical DevOps"]
        assert multiplier == pytest.approx(1.3)

    def test_war_room_synergy(self, calculator: SynergyCalculator) -> None:
        """Planner + coder + reviewer triggers the War Room synergy at 1.5x."""
        roles = [AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER]
        active = calculator.calculate(roles)

        synergy_names = [name for name, _ in active]
        assert "War Room" in synergy_names

        multiplier = dict(active)["War Room"]
        assert multiplier == pytest.approx(1.5)

    def test_no_synergy_single_role(self, calculator: SynergyCalculator) -> None:
        """A single role should not activate any synergy; multiplier stays at 1.0."""
        for role in AgentRole:
            active = calculator.calculate([role])
            assert active == [], f"Expected no synergy for single role {role.value}"
            assert calculator.get_effective_multiplier([role]) == pytest.approx(1.0)

    def test_no_synergy_empty_roles(self, calculator: SynergyCalculator) -> None:
        """An empty role list produces no synergies."""
        assert calculator.calculate([]) == []
        assert calculator.get_effective_multiplier([]) == pytest.approx(1.0)

    def test_multiple_synergies_stack(self, calculator: SynergyCalculator) -> None:
        """Researcher + coder + reviewer activates Surgical DevOps AND Full Stack Review.

        The effective multiplier should be the product: 1.3 * 1.25 = 1.625.
        """
        roles = [AgentRole.RESEARCHER, AgentRole.CODER, AgentRole.REVIEWER]
        active = calculator.calculate(roles)

        synergy_names = {name for name, _ in active}
        assert "Surgical DevOps" in synergy_names, "Expected Surgical DevOps (researcher+coder)"
        assert "Full Stack Review" in synergy_names, "Expected Full Stack Review (coder+reviewer)"

        effective = calculator.get_effective_multiplier(roles)
        expected = 1.3 * 1.25
        assert effective == pytest.approx(expected)

    def test_war_room_stacks_with_sub_synergies(self, calculator: SynergyCalculator) -> None:
        """Planner + coder + reviewer activates War Room plus Full Stack Review.

        War Room requires all three. Full Stack Review requires coder + reviewer.
        Effective multiplier: 1.5 * 1.25 = 1.875.
        """
        roles = [AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER]
        active = calculator.calculate(roles)

        synergy_names = {name for name, _ in active}
        assert "War Room" in synergy_names
        assert "Full Stack Review" in synergy_names

        effective = calculator.get_effective_multiplier(roles)
        expected = 1.5 * 1.25
        assert effective == pytest.approx(expected)

    def test_full_roster_activates_all_applicable(self, calculator: SynergyCalculator) -> None:
        """All roles present should activate every synergy whose requirements are met."""
        roles = list(AgentRole)
        active = calculator.calculate(roles)

        synergy_names = {name for name, _ in active}
        assert "Surgical DevOps" in synergy_names
        assert "Full Stack Review" in synergy_names
        assert "Strategic Planning" in synergy_names
        assert "Customer Intel" in synergy_names
        assert "War Room" in synergy_names

    def test_duplicate_roles_still_satisfy(self, calculator: SynergyCalculator) -> None:
        """Duplicate roles in the list should still activate synergies."""
        roles = [AgentRole.RESEARCHER, AgentRole.CODER, AgentRole.CODER]
        active = calculator.calculate(roles)
        synergy_names = {name for name, _ in active}
        assert "Surgical DevOps" in synergy_names

    def test_add_custom_rule(self, calculator: SynergyCalculator) -> None:
        """Custom rules added via add_rule should be evaluated."""
        custom = SynergyRule(
            name="Test Synergy",
            description="Custom test synergy.",
            required_roles=frozenset({AgentRole.SUPPORT}),
            multiplier=2.0,
        )
        calculator.add_rule(custom)

        active = calculator.calculate([AgentRole.SUPPORT])
        synergy_names = {name for name, _ in active}
        assert "Test Synergy" in synergy_names

        effective = calculator.get_effective_multiplier([AgentRole.SUPPORT])
        assert effective == pytest.approx(2.0)

    def test_get_effective_multiplier_returns_float(
        self, calculator: SynergyCalculator
    ) -> None:
        """Effective multiplier should always be a float."""
        result = calculator.get_effective_multiplier([AgentRole.PLANNER])
        assert isinstance(result, float)
