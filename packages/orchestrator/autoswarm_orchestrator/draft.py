"""Agent drafting logic with weighted role selection and thematic naming."""

from __future__ import annotations

import random

from .types import AgentRole

ROLE_WEIGHTS: dict[AgentRole, float] = {
    AgentRole.PLANNER: 0.15,
    AgentRole.CODER: 0.30,
    AgentRole.REVIEWER: 0.20,
    AgentRole.RESEARCHER: 0.20,
    AgentRole.CRM: 0.10,
    AgentRole.SUPPORT: 0.05,
}

DRAFT_COST: int = 50

_ROLE_NAMES: dict[AgentRole, list[str]] = {
    AgentRole.PLANNER: [
        "Vanguard",
        "Meridian",
        "Compass",
        "Pathfinder",
        "Catalyst",
        "Strategem",
        "Waypoint",
        "Foresight",
    ],
    AgentRole.CODER: [
        "ByteForge",
        "Syntaxia",
        "CodePulse",
        "Kernet",
        "Bitweaver",
        "Stackburn",
        "Hexcraft",
        "LoopSmith",
    ],
    AgentRole.REVIEWER: [
        "SentinelEye",
        "Gatekeeper",
        "LintGuard",
        "Auditor",
        "Watchfire",
        "Critiq",
        "ScopeCheck",
        "Veritas",
    ],
    AgentRole.RESEARCHER: [
        "DeepDive",
        "Luminos",
        "InsightIQ",
        "DataMine",
        "QueryStorm",
        "Cerebrix",
        "Archon",
        "Surveyor",
    ],
    AgentRole.CRM: [
        "RelaySync",
        "PipelineX",
        "DealForge",
        "ClientPulse",
        "Nexus",
        "Rapport",
        "FunnelBot",
        "LeadStream",
    ],
    AgentRole.SUPPORT: [
        "HelpDesk",
        "Responder",
        "TicketWiz",
        "CareBot",
        "EscalateIQ",
        "ResolveX",
        "Patchwork",
        "SafeHarbor",
    ],
}


def draft_agent_role(
    existing_roles: list[AgentRole],
    preference: AgentRole | None = None,
) -> AgentRole:
    """Select a role for a newly drafted agent.

    If *preference* is given it is returned directly.  Otherwise the
    selection uses weighted random choice, down-weighting roles that
    are already over-represented in the current composition.

    Args:
        existing_roles: Roles of all agents already in the swarm.
        preference: Explicitly requested role (bypasses weighting).

    Returns:
        The selected AgentRole.
    """
    if preference is not None:
        return preference

    if not existing_roles:
        roles = list(ROLE_WEIGHTS.keys())
        weights = list(ROLE_WEIGHTS.values())
        return random.choices(roles, weights=weights, k=1)[0]

    total_existing = len(existing_roles)
    role_counts: dict[AgentRole, int] = {}
    for role in existing_roles:
        role_counts[role] = role_counts.get(role, 0) + 1

    adjusted: dict[AgentRole, float] = {}
    for role, base_weight in ROLE_WEIGHTS.items():
        current_fraction = role_counts.get(role, 0) / total_existing
        ideal_fraction = base_weight
        if current_fraction > ideal_fraction:
            penalty = current_fraction / ideal_fraction
            adjusted[role] = max(base_weight / penalty, 0.01)
        else:
            adjusted[role] = base_weight

    roles = list(adjusted.keys())
    weights = list(adjusted.values())
    return random.choices(roles, weights=weights, k=1)[0]


def generate_agent_name(role: AgentRole) -> str:
    """Return a thematic name for the given role, chosen at random."""
    names = _ROLE_NAMES.get(role, ["Agent"])
    return random.choice(names)
