# Project Context Files

Selva supports project-level context files that are automatically injected into ACP system prompts. This allows teams to provide architecture documentation, coding conventions, and agent-specific instructions without modifying the platform.

---

## Supported Files

Files are scanned from the **workspace root** in this order (later files take precedence):

| File | Priority | Purpose |
|---|---|---|
| `CLAUDE.md` | 1 (lowest) | Cross-tool compatibility passthrough |
| `GEMINI.md` | 2 | Cross-tool compatibility passthrough |
| `AGENTS.md` | 3 | Project-level architecture and agent instructions |
| `.selva.md` | 4 (highest) | Workspace-local override |

---

## How to Use

**1. Create an `AGENTS.md` in your project root:**

```markdown
# Project Context

## Architecture
This is a hexagonal (ports & adapters) architecture.
All domain logic lives in `packages/domain/`.
Never import from `apps/` in a `packages/` module.

## Tech Stack
- Backend: FastAPI + SQLAlchemy + Celery
- Frontend: Next.js 14 App Router with Colyseus
- Database: PostgreSQL + Redis

## Agent Instructions
When synthesizing skills for this codebase:
- Always use `async def` for I/O-bound functions
- Follow the existing router pattern in `apps/nexus-api/nexus_api/routers/`
- Run `pytest tests/` before marking a skill complete
```

**2. Optionally add `.selva.md` for workspace-specific overrides:**

```markdown
# Local Override
This workspace is in development mode.
Use localhost:5432 for PostgreSQL.
```

---

## Triggering ACP with Context

Pass `workspace_path` in the ACP initiation request body:

```bash
curl -X POST https://api.selva.yourdomain.com/api/v1/acp/initiate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "workspace_path": "/path/to/your/project"}'
```

If `workspace_path` is provided, `AGENTS.md` and `.selva.md` are injected into Phase I (Analyst) and Phase III (Clean Swarm) system prompts.

---

## Token Budget

Each file is capped at **~8,000 tokens** (~32,000 characters). Files exceeding this limit are truncated with a visible warning marker. Use concise, dense context for best results.

---

## Cross-Tool Compatibility

`CLAUDE.md` and `GEMINI.md` are read as passthrough for interoperability with other AI tools that use the same convention. Their contents are injected at lowest priority and are completely optional.
