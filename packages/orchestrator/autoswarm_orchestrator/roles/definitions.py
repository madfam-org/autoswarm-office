"""Role definitions specifying capabilities and default permissions per agent role."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..types import AgentRole


@dataclass(frozen=True)
class RoleDefinition:
    """Static definition of a swarm agent role's capabilities."""

    role: AgentRole
    display_name: str
    description: str
    default_tools: list[str] = field(default_factory=list)
    default_permissions: dict[str, str] = field(default_factory=dict)


ROLE_DEFINITIONS: dict[AgentRole, RoleDefinition] = {
    AgentRole.PLANNER: RoleDefinition(
        role=AgentRole.PLANNER,
        display_name="Strategic Planner",
        description="Plans and coordinates tasks across the swarm, setting priorities and sequencing work.",
        default_tools=["search", "analyze"],
        default_permissions={"file_read": "allow", "file_write": "deny"},
    ),
    AgentRole.CODER: RoleDefinition(
        role=AgentRole.CODER,
        display_name="Code Engineer",
        description="Writes, refactors, and maintains production code across the codebase.",
        default_tools=["bash", "git", "file_write"],
        default_permissions={
            "file_read": "allow",
            "file_write": "allow",
            "bash_execute": "ask",
            "git_push": "ask",
        },
    ),
    AgentRole.REVIEWER: RoleDefinition(
        role=AgentRole.REVIEWER,
        display_name="Code Reviewer",
        description="Reviews code for correctness, security, and adherence to project standards.",
        default_tools=["file_read", "git"],
        default_permissions={
            "file_read": "allow",
            "file_write": "deny",
            "git_push": "deny",
        },
    ),
    AgentRole.RESEARCHER: RoleDefinition(
        role=AgentRole.RESEARCHER,
        display_name="Research Analyst",
        description="Gathers information, analyses data, and synthesises findings for the team.",
        default_tools=["search", "web", "analyze"],
        default_permissions={"file_read": "allow", "api_call": "allow"},
    ),
    AgentRole.CRM: RoleDefinition(
        role=AgentRole.CRM,
        display_name="CRM Specialist",
        description="Manages customer relationship data, pipeline updates, and outreach.",
        default_tools=["crm_api", "email"],
        default_permissions={"crm_update": "ask", "email_send": "ask"},
    ),
    AgentRole.SUPPORT: RoleDefinition(
        role=AgentRole.SUPPORT,
        display_name="Support Agent",
        description="Handles inbound support tickets, triages issues, and communicates with customers.",
        default_tools=["crm_api", "email", "search"],
        default_permissions={"email_send": "ask", "crm_update": "ask"},
    ),
}
