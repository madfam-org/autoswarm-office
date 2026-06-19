# Selva — Coupler Integration Plan

**Status:** P3a implemented (CouplerToolBackend + registry discovery)  
**Depends on:** Janua P1 (`ConnectedAccount`), Coupler P2 (live execute)  
**Canonical architecture:** [enclii/docs/strategy/AGENT_TOOL_PLANE.md](https://github.com/madfam-org/enclii/blob/main/docs/strategy/AGENT_TOOL_PLANE.md)

**Cross-repo docs (authoritative audit):**

- [coupler/docs/SELVA_TOOLING_AUDIT.md](https://github.com/madfam-org/coupler/blob/main/docs/SELVA_TOOLING_AUDIT.md)
- [coupler/docs/SEPARATION_OF_CONCERNS.md](https://github.com/madfam-org/coupler/blob/main/docs/SEPARATION_OF_CONCERNS.md)
- [coupler/docs/IMPLEMENTATION_ROADMAP.md](https://github.com/madfam-org/coupler/blob/main/docs/IMPLEMENTATION_ROADMAP.md)

---

## 1. Why Selva consumes Coupler

Selva ships **~268 built-in tools** and **6 ecosystem adapters**. Built-ins cover MADFAM workflows; they do **not** replace Composio-class delegated SaaS execution.

| Layer | Owner | Examples |
|-------|-------|----------|
| LLM routing + agent orchestration | Selva | Campaign graph, calibration, HITL |
| Built-in + ecosystem adapters | Selva `packages/tools` | CRM, Dhanam, Karafiel |
| **Delegated SaaS tools** | **Coupler** | `coupler.github.list_repos`, `coupler.slack.post_message` |
| **Operator infra tools** | Enclii Provider Hub | `providers.cloudflare.*`, `ops.*` |
| Identity + OAuth vault | Janua | ConnectedAccount, token delegation |

**Hard rule:** Selva MUST NOT embed connector SDKs for third-party SaaS. Route through Coupler HTTP/MCP.

---

## 2. What stays in Selva (no migration)

| Category | Modules | Reason |
|----------|---------|--------|
| MADFAM ecosystem | `karafiel.py`, `crm_tools.py`, `billing_tools.py`, `legal.py`, `intelligence.py` | Platform API adapters |
| Platform infra | `cloudflare*`, `k8s_*`, `enclii_infra`, `github_admin.py` | Operator / MADFAM org ops |
| Outbound gateway | `email_tools.py` (Resend) | Selva messaging product surface |
| Ingress | `nexus_api/routers/gateway.py` | Channel webhooks, not execute |
| Meta / HITL | `tool_catalog`, `hitl_introspection`, `factory_manifest` | Selva orchestration |
| Worker local | `BashTool`, `GitTool` in workers | Workspace execution |

---

## 3. Migrate to Coupler (P4 refactor targets)

| Selva module | Coupler tool | Notes |
|--------------|--------------|-------|
| `builtins/slack.py` | `coupler.slack.post_message` | Deprecated docstring added; bot token fallback until P4 |
| `mcp_config.json` → `github` | `coupler.github.*` | Use Coupler MCP in dev |
| `packages/calendar/` | future `coupler.google.*` | Per-user OAuth |
| `reddit_tools`, `mastodon_tools`, `bluesky_tools` | future connectors | Persona keys → delegated |

---

## 4. Implementation status

| Phase | Work | Status |
|-------|------|--------|
| **P3a** | `CouplerToolBackend` + `CouplerProxyTool` | ✅ `packages/tools/src/selva_tools/backends/coupler.py` |
| **P3a** | Registry `discover_coupler_tools()` | ✅ behind `SELVA_COUPLER_TOOLS_ENABLED` |
| **P3a** | Unit tests | ✅ `packages/tools/tests/test_coupler_backend.py` |
| **P3b** | Unified `resolve_tools_for_task()` in workers | Planned |
| **P3b** | Pass `user_jwt` via `set_coupler_user_jwt()` in worker | Planned |
| **P3c** | Coupler MCP in labspace `.cursor/mcp.json` | ✅ |
| **P4** | Deprecate direct SaaS HTTP paths | Planned |

---

## 5. `CouplerToolBackend` (implemented)

Location: `packages/tools/src/selva_tools/backends/coupler.py`

```python
class CouplerToolBackend:
    async def list_tools(self, *, user_jwt: str | None = None) -> list[dict]: ...
    async def search_tools(self, query: str, *, user_jwt: str | None = None) -> list[dict]: ...
    async def execute_tool(self, tool_id: str, arguments: dict, *, user_jwt: str | None, ...) -> dict: ...
```

`CouplerProxyTool` registers each Coupler catalog entry into `ToolRegistry` when the feature flag is on.

### Execution context

Workers/graphs must call `set_coupler_user_jwt(token)` before Coupler proxy execute. Selva never stores refresh tokens.

---

## 6. Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `SELVA_COUPLER_TOOLS_ENABLED` | `false` | Register Coupler proxy tools |
| `COUPLER_BASE_URL` | — | Gateway URL |
| `COUPLER_AUDIENCE` | `coupler-api` | JWT audience hint |

---

## 7. Selva internal cleanup (parallel)

1. Wire or remove unused `McpToolAdapter` / ACP MCP bootstrap
2. Unify tool resolution for YAML `tools:` lists and worker graphs
3. Deduplicate Tavily (`web_search` builtin vs `mcp_config.json`)

---

## 8. Trust zones

| Zone | Prefix | Auth |
|------|--------|------|
| User delegated | `coupler.*` | End-user Janua JWT |
| Platform ops | `madfam.ops.*` | Admin JWT → Enclii |
| Built-in | registry names | Tenant/platform audience |

---

## 9. References

- [COUPLER_PROGRAM.md](https://github.com/madfam-org/janua/blob/main/docs/COUPLER_PROGRAM.md)
- [COUPLER_REMEDIATION_PLAN.md](https://github.com/madfam-org/enclii/blob/main/docs/strategy/COUPLER_REMEDIATION_PLAN.md)
