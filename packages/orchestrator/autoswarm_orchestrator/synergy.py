"""Synergy calculation engine inspired by Auto Chess team composition bonuses."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import reduce
from operator import mul

from .types import AgentRole


@dataclass(frozen=True)
class SynergyRule:
    """A synergy rule that activates when all required roles are present."""

    name: str
    description: str
    required_roles: frozenset[AgentRole]
    multiplier: float


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

    def calculate(self, agent_roles: list[AgentRole]) -> list[tuple[str, float]]:
        """Return all synergies whose required roles are satisfied.

        Args:
            agent_roles: Roles present in the current agent composition.

        Returns:
            List of (synergy_name, multiplier) tuples for every active synergy.
        """
        role_set = set(agent_roles)
        return [
            (rule.name, rule.multiplier)
            for rule in self.rules
            if rule.required_roles.issubset(role_set)
        ]

    def get_effective_multiplier(self, agent_roles: list[AgentRole]) -> float:
        """Compute the product of all active synergy multipliers.

        If no synergies are active the effective multiplier is 1.0 (no bonus).
        """
        active = self.calculate(agent_roles)
        if not active:
            return 1.0
        return reduce(mul, (m for _, m in active), 1.0)
