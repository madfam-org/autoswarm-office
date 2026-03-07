"""Tests for SwarmOrchestrator skill-based agent matching."""

from __future__ import annotations

import uuid

from autoswarm_orchestrator.orchestrator import SwarmOrchestrator
from autoswarm_orchestrator.types import AgentConfig, AgentRole, AgentStatus


def _make_orchestrator(*agents: AgentConfig) -> SwarmOrchestrator:
    """Build an orchestrator pre-loaded with agents."""
    orch = SwarmOrchestrator()
    for agent in agents:
        orch.agents[agent.id] = agent
    return orch


def _agent(
    name: str,
    role: AgentRole = AgentRole.CODER,
    skills: list[str] | None = None,
    status: AgentStatus = AgentStatus.IDLE,
) -> AgentConfig:
    return AgentConfig(
        id=str(uuid.uuid4()),
        name=name,
        role=role,
        skill_ids=skills or [],
        status=status,
    )


class TestMatchAgentsBySkills:
    """Tests for SwarmOrchestrator.match_agents_by_skills."""

    def test_returns_matching_agents(self) -> None:
        a1 = _agent("Ada", skills=["coding", "webapp-testing"])
        a2 = _agent("Bob", skills=["research"])
        orch = _make_orchestrator(a1, a2)

        matches = orch.match_agents_by_skills(["coding", "webapp-testing"])
        assert len(matches) == 1
        assert matches[0].name == "Ada"

    def test_ranks_by_overlap_score(self) -> None:
        a1 = _agent("Ada", skills=["coding"])
        a2 = _agent("Bob", skills=["coding", "code-review"])
        orch = _make_orchestrator(a1, a2)

        matches = orch.match_agents_by_skills(["coding", "code-review"])
        assert matches[0].name == "Bob"  # 2/2 overlap > 1/2

    def test_skips_non_idle_agents(self) -> None:
        a1 = _agent("Ada", skills=["coding"], status=AgentStatus.WORKING)
        a2 = _agent("Bob", skills=["coding"], status=AgentStatus.IDLE)
        orch = _make_orchestrator(a1, a2)

        matches = orch.match_agents_by_skills(["coding"])
        assert len(matches) == 1
        assert matches[0].name == "Bob"

    def test_respects_max_agents(self) -> None:
        agents = [_agent(f"Agent-{i}", skills=["coding"]) for i in range(5)]
        orch = _make_orchestrator(*agents)

        matches = orch.match_agents_by_skills(["coding"], max_agents=2)
        assert len(matches) == 2

    def test_empty_required_skills(self) -> None:
        a1 = _agent("Ada", skills=["coding"])
        orch = _make_orchestrator(a1)

        matches = orch.match_agents_by_skills([])
        assert matches == []

    def test_no_overlap_returns_empty(self) -> None:
        a1 = _agent("Ada", skills=["research"])
        orch = _make_orchestrator(a1)

        matches = orch.match_agents_by_skills(["coding"])
        assert matches == []

    def test_agents_without_skills_ignored(self) -> None:
        a1 = _agent("Ada", skills=[])
        a2 = _agent("Bob", skills=["coding"])
        orch = _make_orchestrator(a1, a2)

        matches = orch.match_agents_by_skills(["coding"])
        assert len(matches) == 1
        assert matches[0].name == "Bob"
