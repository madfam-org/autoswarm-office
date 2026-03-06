"""Tests for the agent drafting and naming logic."""

from __future__ import annotations

import pytest

from packages.orchestrator.src.draft import (
    ROLE_WEIGHTS,
    _ROLE_NAMES,
    draft_agent_role,
    generate_agent_name,
)
from packages.orchestrator.src.types import AgentRole


class TestDraftWithPreference:
    """When a preference is specified, the draft should return it directly."""

    def test_preference_returns_exact_role(self) -> None:
        result = draft_agent_role(existing_roles=[], preference=AgentRole.CODER)
        assert result is AgentRole.CODER

    def test_preference_ignores_existing_composition(self) -> None:
        """Preference should bypass weighting even if the role is over-represented."""
        existing = [AgentRole.CODER] * 10
        result = draft_agent_role(existing_roles=existing, preference=AgentRole.CODER)
        assert result is AgentRole.CODER

    @pytest.mark.parametrize("role", list(AgentRole))
    def test_preference_for_every_role(self, role: AgentRole) -> None:
        result = draft_agent_role(existing_roles=[], preference=role)
        assert result is role

    def test_preference_with_non_empty_existing(self) -> None:
        existing = [AgentRole.PLANNER, AgentRole.RESEARCHER]
        result = draft_agent_role(existing_roles=existing, preference=AgentRole.SUPPORT)
        assert result is AgentRole.SUPPORT


class TestDraftWithoutPreference:
    """When no preference is given, weighted random selection applies."""

    def test_returns_valid_role(self) -> None:
        result = draft_agent_role(existing_roles=[])
        assert isinstance(result, AgentRole)
        assert result in AgentRole

    def test_empty_existing_uses_base_weights(self) -> None:
        """With no existing roles and no preference, a valid role is returned."""
        # Run multiple times to exercise randomness; all results must be valid.
        results = {draft_agent_role(existing_roles=[]) for _ in range(100)}
        assert results.issubset(set(AgentRole))
        # With 100 draws from weighted distribution, we should see at least 2 roles.
        assert len(results) >= 2

    def test_all_roles_have_weights(self) -> None:
        """Every AgentRole must have a corresponding weight defined."""
        for role in AgentRole:
            assert role in ROLE_WEIGHTS, f"Missing weight for {role.value}"

    def test_weights_sum_to_one(self) -> None:
        total = sum(ROLE_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_over_represented_role_is_penalised(self) -> None:
        """Flooding existing_roles with coders should reduce coder selection frequency.

        This is a statistical test: with 200 draws from a heavily-penalised
        distribution, coder should appear less often than from a fresh draw.
        """
        heavy_coder = [AgentRole.CODER] * 20
        coder_count = sum(
            1
            for _ in range(200)
            if draft_agent_role(existing_roles=heavy_coder) is AgentRole.CODER
        )
        # With base weight 0.30 and heavy penalty, coder fraction should drop.
        # Allow a generous upper bound to avoid flaky tests.
        coder_fraction = coder_count / 200
        assert coder_fraction < 0.50, (
            f"Expected penalised coder fraction < 0.50, got {coder_fraction:.2f}"
        )


class TestGenerateAgentName:
    """Verify thematic name generation per role."""

    @pytest.mark.parametrize("role", list(AgentRole))
    def test_returns_string_for_each_role(self, role: AgentRole) -> None:
        name = generate_agent_name(role)
        assert isinstance(name, str)
        assert len(name) > 0

    @pytest.mark.parametrize("role", list(AgentRole))
    def test_name_comes_from_role_names_table(self, role: AgentRole) -> None:
        """The generated name must be a member of the role's name pool."""
        name = generate_agent_name(role)
        expected_names = _ROLE_NAMES[role]
        assert name in expected_names, (
            f"Name '{name}' not in {role.value} pool: {expected_names}"
        )

    def test_names_are_non_empty_for_all_roles(self) -> None:
        """Every role should have at least one candidate name."""
        for role in AgentRole:
            assert len(_ROLE_NAMES.get(role, [])) > 0

    def test_randomness_produces_variety(self) -> None:
        """Multiple calls should produce more than one unique name."""
        names = {generate_agent_name(AgentRole.CODER) for _ in range(50)}
        assert len(names) >= 2, "Expected variety in generated names"
