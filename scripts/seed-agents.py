#!/usr/bin/env python3
"""Seed default departments, agent templates, permission matrix, and synergy rules.

Usage:
    # Seed via the Nexus API (requires the server to be running on port 4300):
    python scripts/seed-agents.py

    # Export seed data as JSON files instead of calling the API:
    python scripts/seed-agents.py --json-only

The script is idempotent: departments are matched by slug, so re-running
it will not create duplicates when using the API.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore[assignment]

API_BASE = "http://localhost:4300/api/v1"

# ── Default Departments ──────────────────────────────────────────────

DEPARTMENTS = [
    {
        "name": "Engineering",
        "slug": "engineering",
        "description": "Software development, code review, and deployment operations.",
        "max_agents": 8,
        "position_x": 100,
        "position_y": 100,
    },
    {
        "name": "Research",
        "slug": "research",
        "description": "Market research, data analysis, and strategic intelligence.",
        "max_agents": 4,
        "position_x": 400,
        "position_y": 100,
    },
    {
        "name": "CRM",
        "slug": "crm",
        "description": "Customer relationship management and pipeline operations.",
        "max_agents": 4,
        "position_x": 100,
        "position_y": 400,
    },
    {
        "name": "Support",
        "slug": "support",
        "description": "Customer support ticket triage and resolution.",
        "max_agents": 4,
        "position_x": 400,
        "position_y": 400,
    },
]

# ── Starter Agent Templates ─────────────────────────────────────────

AGENT_TEMPLATES = [
    {"name": "Archie", "role": "planner", "level": 2, "department_slug": "engineering"},
    {"name": "Nova", "role": "coder", "level": 1, "department_slug": "engineering"},
    {"name": "Sentinel", "role": "reviewer", "level": 1, "department_slug": "engineering"},
    {"name": "Iris", "role": "researcher", "level": 1, "department_slug": "research"},
    {"name": "Pulse", "role": "crm", "level": 1, "department_slug": "crm"},
    {"name": "Echo", "role": "support", "level": 1, "department_slug": "support"},
]

# ── Default Permission Matrix ───────────────────────────────────────

DEFAULT_PERMISSION_MATRIX = {
    "file_read": "allow",
    "file_write": "ask",
    "bash_execute": "ask",
    "git_commit": "ask",
    "git_push": "ask",
    "email_send": "ask",
    "crm_update": "ask",
    "deploy": "ask",
    "api_call": "allow",
}

# ── Synergy Rules ────────────────────────────────────────────────────

SYNERGY_RULES = [
    {
        "name": "Surgical DevOps",
        "description": "Researcher gathers context while coder implements with precision.",
        "required_roles": ["researcher", "coder"],
        "multiplier": 1.3,
    },
    {
        "name": "Full Stack Review",
        "description": "Coder and reviewer form a tight feedback loop.",
        "required_roles": ["coder", "reviewer"],
        "multiplier": 1.25,
    },
    {
        "name": "Strategic Planning",
        "description": "Planner and researcher combine vision with evidence.",
        "required_roles": ["planner", "researcher"],
        "multiplier": 1.2,
    },
    {
        "name": "Customer Intel",
        "description": "CRM and support share frontline customer insights.",
        "required_roles": ["crm", "support"],
        "multiplier": 1.15,
    },
    {
        "name": "War Room",
        "description": "Planner, coder, and reviewer execute with full-spectrum coordination.",
        "required_roles": ["planner", "coder", "reviewer"],
        "multiplier": 1.5,
    },
]


# ── API Seeding ──────────────────────────────────────────────────────


def seed_via_api() -> None:
    """POST seed data to the running Nexus API."""
    if httpx is None:
        print("httpx is not installed. Install with: uv pip install httpx")
        print("Falling back to JSON output mode.\n")
        write_json_files()
        return

    client = httpx.Client(
        base_url=API_BASE,
        timeout=10.0,
        headers={"Authorization": "Bearer dev-token"},
    )

    # Check API health first.
    try:
        health = client.get("/health/health")
        health.raise_for_status()
    except (httpx.ConnectError, httpx.HTTPStatusError):
        print(f"Cannot reach Nexus API at {API_BASE}")
        print("Start the server with 'make dev' or use --json-only to export JSON.\n")
        print("Falling back to JSON output mode.\n")
        write_json_files()
        return

    print("Connected to Nexus API\n")

    # Seed departments and collect slug -> id mapping.
    dept_ids: dict[str, str] = {}
    for dept in DEPARTMENTS:
        resp = client.post("/departments/", json=dept)
        if resp.status_code == 201:
            data = resp.json()
            dept_ids[dept["slug"]] = data["id"]
            print(f"  Created department: {dept['name']} ({data['id']})")
        elif resp.status_code == 409:
            # Already exists -- fetch the list to find the id.
            list_resp = client.get("/departments/")
            for d in list_resp.json():
                if d["slug"] == dept["slug"]:
                    dept_ids[dept["slug"]] = d["id"]
            print(f"  Department already exists: {dept['name']}")
        else:
            print(f"  Failed to create department {dept['name']}: {resp.status_code} {resp.text}")

    print()

    # Seed agents.
    for tmpl in AGENT_TEMPLATES:
        dept_slug = tmpl.pop("department_slug")
        dept_id = dept_ids.get(dept_slug)
        if dept_id:
            tmpl["department_id"] = dept_id

        resp = client.post("/agents/", json=tmpl)
        if resp.status_code == 201:
            data = resp.json()
            print(f"  Created agent: {tmpl['name']} [{tmpl['role']}] ({data['id']})")
        else:
            print(f"  Failed to create agent {tmpl['name']}: {resp.status_code} {resp.text}")

        # Restore the slug for potential re-run.
        tmpl["department_slug"] = dept_slug
        tmpl.pop("department_id", None)

    print("\nSeed complete.")
    client.close()


# ── JSON File Output ─────────────────────────────────────────────────


def write_json_files() -> None:
    """Write seed data as JSON files to data/seed/."""
    seed_dir = Path("data/seed")
    seed_dir.mkdir(parents=True, exist_ok=True)

    seed_data = {
        "departments": DEPARTMENTS,
        "agent_templates": AGENT_TEMPLATES,
        "permission_matrix": DEFAULT_PERMISSION_MATRIX,
        "synergy_rules": SYNERGY_RULES,
    }

    output_path = seed_dir / "seed-data.json"
    output_path.write_text(json.dumps(seed_data, indent=2) + "\n")
    print(f"Seed data written to {output_path}")

    # Also write individual files for easy consumption.
    for key, data in seed_data.items():
        path = seed_dir / f"{key.replace('_', '-')}.json"
        path.write_text(json.dumps(data, indent=2) + "\n")
        print(f"  {path}")

    print()


# ── Main ─────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed AutoSwarm Office defaults")
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="Write seed data as JSON files instead of calling the API",
    )
    args = parser.parse_args()

    if args.json_only:
        write_json_files()
    else:
        seed_via_api()


if __name__ == "__main__":
    main()
