"""Synergy calculation engine inspired by Auto Chess team composition bonuses."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce
from operator import mul

from .types import AgentRole


@dataclass(frozen=True)
class SynergyRule:
    """A synergy rule that activates when all required roles and skills are present."""

    name: str
    description: str
    required_roles: frozenset[AgentRole]
    multiplier: float
    required_skills: frozenset[str] = frozenset()


_DEFAULT_SYNERGY_RULES: list[SynergyRule] = [
    SynergyRule(
        name="Surgical DevOps",
        description="Researcher gathers context while coder implements with precision.",
        required_roles=frozenset({AgentRole.RESEARCHER, AgentRole.CODER}),
        multiplier=1.3,
    ),
    SynergyRule(
        name="Full Stack Review",
        description="Coder and reviewer form a tight feedback loop.",
        required_roles=frozenset({AgentRole.CODER, AgentRole.REVIEWER}),
        multiplier=1.25,
    ),
    SynergyRule(
        name="Strategic Planning",
        description="Planner and researcher combine vision with evidence.",
        required_roles=frozenset({AgentRole.PLANNER, AgentRole.RESEARCHER}),
        multiplier=1.2,
    ),
    SynergyRule(
        name="Customer Intel",
        description="CRM and support share frontline customer insights.",
        required_roles=frozenset({AgentRole.CRM, AgentRole.SUPPORT}),
        multiplier=1.15,
    ),
    SynergyRule(
        name="War Room",
        description="Planner, coder, and reviewer execute with full-spectrum coordination.",
        required_roles=frozenset({AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER}),
        multiplier=1.5,
    ),
    SynergyRule(
        name="Full Coverage",
        description="Coding, code-review, and webapp-testing skills provide end-to-end quality.",
        required_roles=frozenset(),
        required_skills=frozenset({"coding", "code-review", "webapp-testing"}),
        multiplier=1.35,
    ),
    SynergyRule(
        name="MADFAM Expert",
        description="MADFAM API knowledge combined with coder role accelerates platform work.",
        required_roles=frozenset({AgentRole.CODER}),
        required_skills=frozenset({"madfam-api"}),
        multiplier=1.15,
    ),
    SynergyRule(
        name="Research Pipeline",
        description="Research and doc-coauthoring skills streamline knowledge production.",
        required_roles=frozenset(),
        required_skills=frozenset({"research", "doc-coauthoring"}),
        multiplier=1.2,
    ),
]


@dataclass
class SynergyCalculator:
    """Evaluates active synergies for a given set of agent roles.

    Synergy rules fire when every required role is present in the
    working set.  Multiple synergies can stack multiplicatively.
    """

    rules: list[SynergyRule] = field(default_factory=lambda: list(_DEFAULT_SYNERGY_RULES))

    def add_rule(self, rule: SynergyRule) -> None:
        """Register an additional synergy rule."""
        self.rules.append(rule)

    def calculate(
        self,
        agent_roles: list[AgentRole],
        agent_skills: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        """Return all synergies whose required roles and skills are satisfied.

        Args:
            agent_roles: Roles present in the current agent composition.
            agent_skills: Skills present across all agents (optional).

        Returns:
            List of (synergy_name, multiplier) tuples for every active synergy.
        """
        role_set = set(agent_roles)
        skill_set = set(agent_skills or [])
        return [
            (rule.name, rule.multiplier)
            for rule in self.rules
            if rule.required_roles.issubset(role_set)
            and rule.required_skills.issubset(skill_set)
        ]

    def get_effective_multiplier(
        self,
        agent_roles: list[AgentRole],
        agent_skills: list[str] | None = None,
    ) -> float:
        """Compute the product of all active synergy multipliers.

        If no synergies are active the effective multiplier is 1.0 (no bonus).
        """
        active = self.calculate(agent_roles, agent_skills)
        if not active:
            return 1.0
        return reduce(mul, (m for _, m in active), 1.0)
