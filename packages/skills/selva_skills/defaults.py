"""Default role-to-skill mappings for Selva agents."""

from __future__ import annotations

DEFAULT_ROLE_SKILLS: dict[str, list[str]] = {
    "planner": ["strategic-planning", "research"],
    "coder": ["coding"],
    "reviewer": ["code-review"],
    "researcher": ["research", "doc-coauthoring"],
    "crm": ["crm-outreach"],
    "support": ["customer-support"],
}
