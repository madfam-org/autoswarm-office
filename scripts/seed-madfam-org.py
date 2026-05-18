#!/usr/bin/env python3
"""
Seed the MADFAM organizational structure into AutoSwarm Office.

4 Nodes, 10 Primary Agents:
  - Node 1: Executive Brain Trust (Oráculo, Centinela, Forjador)
  - Node 2: Build & Run Engine (Telar, Códice, Vigía)
  - Node 3: Growth & Market Syndicate (Heraldo, Nexo)
  - Node 4: Physical-Digital Bridge (Áureo, Espectro)

Usage:
  python scripts/seed-selva-org.py [--api-url URL] [--token TOKEN]
"""

import argparse
import os
import sys

import httpx

API_URL = os.environ.get("AUTOSWARM_API_URL", "https://api.selva.town")
TOKEN = os.environ.get("AUTOSWARM_TOKEN", "dev-bypass")
ORG_ID = os.environ.get("AUTOSWARM_ORG_ID", "madfam")

# ─── Departments ──────────────────────────────────────────────────────────────

DEPARTMENTS = [
    {
        "name": "Executive Brain Trust",
        "slug": "executive",
        "description": (
            "Strategic oversight, risk analysis, architectural vision."
            " Read-heavy, decision-making node."
        ),
        "max_agents": 6,
        "position_x": 250,
        "position_y": 100,
    },
    {
        "name": "Build & Run Engine",
        "slug": "build-engine",
        "description": (
            "Product execution, code delivery, infrastructure reliability. The execution backbone."
        ),
        "max_agents": 12,
        "position_x": 750,
        "position_y": 100,
    },
    {
        "name": "Growth & Market Syndicate",
        "slug": "growth",
        "description": (
            "Market analysis, content creation, customer relationships, conversion optimization."
        ),
        "max_agents": 8,
        "position_x": 250,
        "position_y": 500,
    },
    {
        "name": "Physical-Digital Bridge",
        "slug": "operations",
        "description": (
            "Financial control, supply chain, manufacturing orchestration, digital twin management."
        ),
        "max_agents": 6,
        "position_x": 750,
        "position_y": 500,
    },
]

# ─── Agents ───────────────────────────────────────────────────────────────────

AGENTS = [
    # ═══ EXECUTIVE NODE (Chief of Staff) ═══
    {
        "name": "Oráculo",
        "role": "planner",
        "level": 10,
        "department_slug": "executive",
        "node_id": "executive",
        "skill_ids": ["strategic-planning", "research", "product-catalog", "vault-break-glass"],
    },
    {
        "name": "Centinela",
        "role": "planner",
        "level": 9,
        "department_slug": "executive",
        "node_id": "executive",
        "skill_ids": [
            "strategic-planning",
            "crm-outreach",
            "research",
            "doc-coauthoring",
            "product-catalog",
            "incident-triage",
        ],
    },
    # ═══ BUILD NODE ═══
    {
        "name": "Telar",
        "role": "planner",
        "level": 7,
        "department_slug": "build-engine",
        "node_id": "build",
        "skill_ids": [
            "strategic-planning",
            "doc-coauthoring",
            "webapp-testing",
            "research",
            "staging-refresh",
        ],
    },
    {
        "name": "Códice",
        "role": "coder",
        "level": 9,
        "department_slug": "build-engine",
        "node_id": "build",
        "skill_ids": [
            "coding",
            "code-review",
            "research",
            "webapp-testing",
            "doc-coauthoring",
            "cluster-triage",
        ],
    },
    # ═══ GROWTH NODE (The Catalyst) ═══
    {
        "name": "Heraldo",
        "role": "researcher",
        "level": 8,
        "department_slug": "growth",
        "node_id": "growth",
        "skill_ids": ["research", "crm-outreach", "doc-coauthoring", "strategic-planning"],
    },
    {
        "name": "Nexo",
        "role": "crm",
        "level": 8,
        "department_slug": "growth",
        "node_id": "growth",
        "skill_ids": ["crm-outreach", "customer-support", "research", "doc-coauthoring"],
    },
    # ═══ ORCHESTRATION NODE (Biological Siphoning) ═══
    {
        "name": "Forjador",
        "role": "planner",
        "level": 10,
        "department_slug": "executive",
        "node_id": "orchestration",
        "skill_ids": [
            "strategic-planning",
            "coding",
            "code-review",
            "research",
            "mcp-builder",
            "vault-break-glass",
            "incident-triage",
        ],
    },
    {
        "name": "Vigía",
        "role": "coder",
        "level": 8,
        "department_slug": "build-engine",
        "node_id": "orchestration",
        "skill_ids": [
            "coding",
            "webapp-testing",
            "mcp-builder",
            "research",
            "operations",
            "infrastructure-monitoring",
            "cluster-triage",
            "vault-break-glass",
        ],
    },
    # ═══ LEDGER NODE ═══
    {
        "name": "Áureo",
        "role": "researcher",
        "level": 7,
        "department_slug": "operations",
        "node_id": "ledger",
        "skill_ids": ["research", "doc-coauthoring", "strategic-planning", "product-catalog"],
    },
    # ═══ PHYGITAL NODE (Yantra4D Engine) ═══
    {
        "name": "Espectro",
        "role": "coder",
        "level": 7,
        "department_slug": "operations",
        "node_id": "phygital",
        "skill_ids": ["coding", "research", "mcp-builder"],
    },
]


def api(method: str, path: str, data: dict | None = None) -> dict | list | None:
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "X-Selva-Tenant-Org": ORG_ID,
    }
    url = f"{API_URL}{path}"
    try:
        if method == "GET":
            r = httpx.get(url, headers=headers, timeout=10)
        elif method == "POST":
            r = httpx.post(url, headers=headers, json=data, timeout=10)
        elif method == "PUT":
            r = httpx.put(url, headers=headers, json=data, timeout=10)
        elif method == "DELETE":
            r = httpx.delete(url, headers=headers, timeout=10)
        else:
            raise ValueError(f"Unknown method: {method}")
        if r.status_code in (200, 201):
            return r.json()
        if r.status_code == 204:
            return None
        print(f"  ⚠  {method} {path} → {r.status_code}: {r.text[:200]}")
        return None
    except Exception as e:
        print(f"  ✗  {method} {path} → {e}")
        return None


def seed_departments() -> dict[str, str]:
    """Create departments, return slug→id mapping."""
    print("\n═══ Departments ═══")
    existing_response = api("GET", "/api/v1/departments/") or []
    existing = (
        existing_response.get("items", [])
        if isinstance(existing_response, dict)
        else existing_response
    )
    slug_to_id: dict[str, str] = {}

    for dept in existing:
        slug_to_id[dept["slug"]] = dept["id"]

    for dept_def in DEPARTMENTS:
        if dept_def["slug"] in slug_to_id:
            print(f"  ✓  {dept_def['name']} (exists)")
            continue
        result = api("POST", "/api/v1/departments/", dept_def)
        if result:
            slug_to_id[result["slug"]] = result["id"]
            print(f"  ✚  {dept_def['name']} → {result['id']}")
        else:
            print(f"  ✗  Failed to create {dept_def['name']}")

    return slug_to_id


def seed_agents(dept_map: dict[str, str]) -> None:
    """Create or reconcile agents in their departments."""
    print("\n═══ Agents ═══")
    existing_response = api("GET", "/api/v1/agents/") or []
    existing_agents = (
        existing_response.get("items", [])
        if isinstance(existing_response, dict)
        else existing_response
    )
    existing_by_name = {a["name"]: a for a in existing_agents}

    for agent_def in AGENTS:
        existing_agent = existing_by_name.get(agent_def["name"])
        if existing_agent is not None:
            current_skills = existing_agent.get("skill_ids") or []
            desired_skills = agent_def["skill_ids"]
            if current_skills == desired_skills:
                print(f"  ✓  {agent_def['name']} (exists)")
                continue

            payload = {
                "role": agent_def["role"],
                "level": agent_def["level"],
                "skill_ids": desired_skills,
            }
            result = api("PUT", f"/api/v1/agents/{existing_agent['id']}", payload)
            if result:
                added = sorted(set(desired_skills) - set(current_skills))
                suffix = f" +{', '.join(added)}" if added else ""
                print(f"  ↻  {agent_def['name']} skills reconciled{suffix}")
            else:
                print(f"  ✗  Failed to update {agent_def['name']}")
            continue

        dept_id = dept_map.get(agent_def["department_slug"])
        if not dept_id:
            print(
                f"  ✗  {agent_def['name']} — department '{agent_def['department_slug']}' not found",
            )
            continue

        payload = {
            "name": agent_def["name"],
            "role": agent_def["role"],
            "level": agent_def["level"],
            "department_id": dept_id,
            "skill_ids": agent_def["skill_ids"],
        }

        result = api("POST", "/api/v1/agents/", payload)
        if result:
            print(
                f"  ✚  {agent_def['name']} [{agent_def['role']}] → {agent_def['department_slug']}",
            )
        else:
            print(f"  ✗  Failed to create {agent_def['name']}")


def main():
    parser = argparse.ArgumentParser(description="Seed MADFAM org structure")
    parser.add_argument("--api-url", default=API_URL)
    parser.add_argument("--token", default=TOKEN)
    parser.add_argument("--org-id", default=ORG_ID)
    args = parser.parse_args()

    # Override module-level config from CLI args
    globals()["API_URL"] = args.api_url
    globals()["TOKEN"] = args.token
    globals()["ORG_ID"] = args.org_id

    print(f"🏛  Seeding MADFAM organization at {args.api_url}")
    print(f"   Org: {args.org_id}")
    print(f"   Token: {'provided' if args.token else 'missing'}")

    # Health check
    health = api("GET", "/api/v1/health/health")
    if not health:
        print("✗  API unreachable")
        sys.exit(1)
    print(f"✓  API healthy: {health.get('status', 'unknown')}")

    dept_map = seed_departments()
    seed_agents(dept_map)

    print(f"\n✅  MADFAM org seeded: {len(DEPARTMENTS)} departments, {len(AGENTS)} agents")


if __name__ == "__main__":
    main()
