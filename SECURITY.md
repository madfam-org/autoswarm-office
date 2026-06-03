# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in Selva Office, please report it responsibly:

1. **Do not** open a public GitHub issue
2. Email security@selva.town with details
3. Include steps to reproduce if possible
4. We will acknowledge receipt within 48 hours

## Sensitive Data

This project handles sensitive data including:
- LLM provider API keys (OpenAI, Anthropic, etc.)
- Agent orchestration data and execution logs
- Real-time collaboration session data (Colyseus)
- User authentication tokens and session state
- Database credentials and connection strings

### Rules

- API keys and LLM credentials must **never** be committed to version control
- All secrets must be provided via environment variables or K8s secrets
- Agent execution logs must not contain user PII or credentials
- Colyseus room state must not persist sensitive data beyond session lifetime
- Logs must never contain passwords, tokens, or API keys

## Known Security Exceptions

### Demo Mode Token Bypass

Selva Office includes a public demo mode (`/demo`) that allows unauthenticated visitors to experience the office environment with simulated agents. This mode intentionally bypasses the normal Janua JWKS authentication flow.

#### What the bypass does

The demo page generates an **unsigned JWT** on the client side with the following claims:

| Claim | Value | Purpose |
|-------|-------|---------|
| `org_id` | `demo-public` | Identifies all demo sessions as belonging to a synthetic organization |
| `roles` | `["demo"]` | Grants the minimum role required to join a Colyseus room |

The Colyseus server's `verifyToken()` function recognizes tokens with `org_id: "demo-public"` and skips JWKS signature verification for those tokens only. All other tokens proceed through the standard Janua JWKS validation path.

#### Why it exists

The demo mode is a product requirement for the landing page. Visitors must be able to try the office experience without creating an account or authenticating through Janua. Requiring real authentication for a sandbox demo would defeat its purpose as a low-friction onboarding tool.

#### Isolation measures

The following controls ensure the demo bypass cannot be used to access real data or disrupt authenticated users:

1. **Room isolation.** Colyseus rooms are filtered by `orgId` via `filterBy(["orgId"])`. Demo rooms (`orgId: "demo-public"`) are completely separate from production rooms. A demo token cannot join or observe a real organization's room.

2. **Simulated agents only.** The `DemoSimulator` populates 8 hardcoded agents that cycle through states on a timer. These agents are not connected to the worker process, nexus-api, or any real task queue. No actual LLM inference, git operations, or file system access occurs.

3. **Feature restrictions.** The `OfficeExperience` component accepts a `mode` parameter. In `demo` mode, the following features are hidden and their hooks skip all API calls and WebSocket connections:
   - Calendar integration (`useCalendar`)
   - Skill marketplace (`useMarketplace`)
   - Map editor
   - Workflow editor
   - Ops feed and metrics (`useEventStream`)
   - Task dispatch (`useTaskDispatch`)
   - Approval queue (`useApprovals`)
   - Task board (`useTaskBoard`)

4. **No API access.** Demo tokens do not carry a valid signature. Any request from a demo client to nexus-api endpoints that require Bearer authentication will be rejected by the standard JWT validation middleware. The bypass exists only in the Colyseus `onAuth` path.

5. **No data persistence.** Demo room state is ephemeral. When the last demo client disconnects, the room is destroyed. No demo data is written to PostgreSQL, Redis streams, or the artifact storage.

6. **Auto-approval timeout.** The `DemoSimulator` auto-approves pending approvals after 15 seconds if no human action occurs, preventing simulated agents from accumulating stale state.

#### Monitoring approach

- **Room metrics.** The Colyseus health endpoint (`GET :4303/health`) reports active rooms by `orgId`. Abnormal growth in `demo-public` rooms is visible in Grafana dashboards and triggers a Prometheus alert if count exceeds the threshold.
- **Connection rate.** The dispatch rate limiter (`MessageRateLimiter`, 10 req/60s per user) applies equally to demo connections. Rapid reconnection attempts are throttled at the WebSocket transport layer.
- **Log tagging.** All Colyseus log entries for demo rooms include `org_id=demo-public`, making it straightforward to filter demo traffic from production traffic in log aggregation.
- **No secret exposure.** Because demo mode does not invoke the worker process, LLM providers, or nexus-api authenticated endpoints, there is no path from demo mode to secret material (API keys, database credentials, GitHub tokens).

#### Risk assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| Demo token used to join a real org room | Low | `filterBy(["orgId"])` prevents cross-org room access |
| Demo token used to call nexus-api | Low | Standard JWT validation rejects unsigned tokens |
| Resource exhaustion from demo room creation | Medium | Rate limiting on WebSocket connections; room auto-destroy on disconnect |
| Demo mode used as amplification vector | Low | No outbound API calls, no LLM inference, no git operations in demo path |

#### Configuration

Demo mode is controlled by the `NEXT_PUBLIC_DEMO_ENABLED` environment variable (default: `true`). Setting it to `false` hides the "Try Demo" CTA on the landing page and prevents the demo page from rendering. The Colyseus demo token bypass remains in code but is unreachable without the client-side entry point.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.2.x   | Yes       |
