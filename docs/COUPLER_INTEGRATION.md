# Selva — Coupler Integration Plan

**Status:** planned (P3 consumer PoC)  
**Depends on:** Janua P1 (ConnectedAccount), Coupler P2 (gateway + executor)  
**Canonical architecture:** [enclii/docs/strategy/AGENT_TOOL_PLANE.md](https://github.com/madfam-org/enclii/blob/main/docs/strategy/AGENT_TOOL_PLANE.md)

---

## 1. Why Selva consumes Coupler

Selva today ships **268 built-in tools** and **6 ecosystem adapters** (Karafiel, Dhanam, PhyndCRM, Tezca, Crawler, A2A). Built-ins cover platform-specific workflows; they do **not** replace Composio-class delegated SaaS execution (Slack, Gmail, GitHub as end-user, Notion, etc.).

| Layer | Owner | Examples |
|-------|-------|----------|
| LLM routing + agent orchestration | Selva (Nexus, workers, graphs) | Campaign graph, calibration, HITL |
| Built-in + ecosystem adapters | Selva `packages/tools` | CRM handoff, Dhanam, email gateways |
| **Delegated SaaS tools** | **Coupler** | `github.list_repos`, `slack.post_message` |
| **Operator infra tools** | Enclii Provider Hub | `providers.cloudflare.*`, `ops.*` |
| Identity + OAuth vault | Janua | ConnectedAccount, token delegation |

**Hard rule:** Selva MUST NOT embed connector SDKs for third-party SaaS. Route through Coupler HTTP/MCP.

---

## 2. Integration phases (aligned with Coupler program)

| Phase | Selva work | Gate |
|-------|------------|------|
| **P3a** | `CouplerToolBackend` in `packages/tools` — search + execute via Coupler REST | Staging smoke: one tool call |
| **P3b** | Wire backend into agent graph tool resolver (feature flag) | Worker e2e with mocked Coupler |
| **P3c** | MCP client path for Cursor/dev agents (optional parallel) | MCP smoke doc |
| **P4** | Replace any direct SaaS HTTP in adapters with Coupler | Parity checklist |
| **P5** | Synthetics: agent invokes Slack via Coupler on staging | Green in Enclii-style gate |

Target: **2026-10-03** for P3 PoC (Coupler program calendar).

---

## 3. Proposed `CouplerToolBackend` interface

Location (planned): `packages/tools/src/selva_tools/backends/coupler.py`

```python
class CouplerToolBackend:
    """Resolve tool definitions and execute via Coupler gateway."""

    async def search_tools(self, query: str, *, user_jwt: str) -> list[ToolDefinition]: ...
    async def execute_tool(
        self,
        tool_id: str,
        arguments: dict,
        *,
        user_jwt: str,
        connection_id: str | None = None,
    ) -> ToolResult: ...
```

Environment:

| Variable | Description |
|----------|-------------|
| `COUPLER_BASE_URL` | Gateway URL (staging/prod) |
| `COUPLER_AUDIENCE` | `coupler-api` |
| `JANUA_ISSUER_URL` | Passthrough user JWT validation context |

User JWT is forwarded to Coupler; Coupler calls Janua for delegation. Selva never sees refresh tokens.

---

## 4. Trust zones in Selva agents

| Zone | Tool prefix | Auth | Use case |
|------|-------------|------|----------|
| **User delegated** | `coupler.*` / connector ids | End-user Janua JWT | Slack, Gmail, GitHub-as-user |
| **Platform ops** | `madfam.ops.*` | Admin JWT (Enclii audience) | DNS, deploy, provider hub |
| **Built-in** | existing registry | Tenant/platform audience | Campaign, CRM, internal |

Operator tools stay on Enclii; Coupler proxies `madfam.ops.*` only for admin-scoped agents (Coupler P4).

---

## 5. What stays in Selva (no migration)

- All 268 built-in tools unless they duplicate a Coupler connector
- Messaging gateways (18 channels) — different surface than Coupler execute
- Ecosystem adapters (Karafiel, Dhanam, PhyndCRM, Tezca, Crawler, A2A)
- LLM inference routing (Selva Nexus `/v1`)

---

## 6. Testing strategy

1. **Unit:** mock Coupler OpenAPI responses in `packages/tools/tests/`
2. **Integration:** staging Coupler + Janua test user with GitHub connection
3. **Load:** defer to Coupler gate; Selva adds k6 scenario only after P3 PoC
4. **Feature flag:** `SELVA_COUPLER_TOOLS_ENABLED` default `false` until P3 gate

---

## 7. References

- [COUPLER_REMEDIATION_PLAN.md](https://github.com/madfam-org/enclii/blob/main/docs/strategy/COUPLER_REMEDIATION_PLAN.md) — task IDs S3-*
- [janua/docs/COUPLER_PROGRAM.md](https://github.com/madfam-org/janua/blob/main/docs/COUPLER_PROGRAM.md) — token delegation contract
- [AUTONOMOUS_OPERATIONS_PROGRAM.md](./AUTONOMOUS_OPERATIONS_PROGRAM.md) — Phases 0–6 (Coupler enables Phase 5+ external tool breadth)
