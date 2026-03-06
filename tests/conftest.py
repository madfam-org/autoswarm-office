"""Root-level shared fixtures for the AutoSwarm Office test suite."""

from __future__ import annotations

import pytest

from packages.orchestrator.src.types import AgentRole


@pytest.fixture()
def all_roles() -> list[AgentRole]:
    """Return every AgentRole member as a list."""
    return list(AgentRole)


@pytest.fixture()
def coder_researcher_pair() -> list[AgentRole]:
    """Common two-role composition: researcher + coder."""
    return [AgentRole.RESEARCHER, AgentRole.CODER]


@pytest.fixture()
def war_room_trio() -> list[AgentRole]:
    """Common three-role composition: planner + coder + reviewer."""
    return [AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER]
