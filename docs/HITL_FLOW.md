# Human-in-the-Loop (HITL) Flow

Selva Office enforces a zero-surprise architecture where all destructive or
outbound agent actions require explicit human approval before execution.

**Autonomy graduation:** Lanes move from **ask** → **allow** per
[AUTONOMOUS_OPERATIONS_PROGRAM.md § Phase 6](./AUTONOMOUS_OPERATIONS_PROGRAM.md#phase-6--autonomy-graduation-ongoing-from-phase-1)
after a documented clean-run period — never by default.

## Permission Matrix

The default permission matrix defines which actions agents can take autonomously
and which require Tactician approval.

| Action Category | Default Level | Description |
|----------------|--------------|-------------|
| `file_read` | **allow** | Read files from the filesystem or repos |
| `file_write` | **ask** | Write or modify files |
| `bash_execute` | **ask** | Execute shell commands |
| `git_commit` | **ask** | Create git commits |
| `git_push` | **ask** | Push commits to remote repositories |
| `email_send` | **ask** | Send outbound emails |
| `crm_update` | **ask** | Modify CRM records or pipeline data |
| `deploy` | **ask** | Trigger deployment pipelines |
| `api_call` | **allow** | Make outbound API requests (read-only) |

Permission levels:
- **allow** -- Agent executes immediately without human involvement.
- **ask** -- Agent execution pauses; the Tactician must approve or deny.
- **deny** -- Action is blocked entirely; agent cannot request it.

The matrix is defined in `packages/permissions/src/matrix.py` and can be customized
per-organization or per-department.

### Permission Enforcement in Graph Nodes

The permission engine is wired into graph execution nodes via the
`check_permission()` helper in `apps/workers/selva_workers/graphs/base.py`:

- **Coding graph `implement()`**: Checks `file_write` before writing files to the
  worktree. Returns `status: "blocked"` on DENY.
- **CRM graph `send()`**: Checks `email_send` before sending outbound communication.
  Returns `status: "blocked"` on DENY.
- **Coding graph `push_gate()`**: Uses `interrupt()` for ASK-level approval of
  `git_push`. On approval, calls `git_tool.commit()` + `git_tool.push()`.
- **Skill overrides**: When `agent_skill_ids` are present, `_build_engine_for_state()`
  creates a `PermissionEngine` with skill-based overrides that can ALLOW actions
  that would otherwise require approval.

## Interrupt Mechanism

When an agent attempts an action classified as `ask`, the following occurs inside
the LangGraph execution graph:

1. The tool node calls the permission engine to evaluate the action category.
2. The engine returns `requires_approval: true`.
3. The tool node invokes LangGraph's `interrupt()` function, which serializes the
   current graph state and pauses execution.
4. The interrupt payload (action details, diff, reasoning) is sent to the Nexus API
   via the Redis task queue.
5. The Nexus API persists an `ApprovalRequest` row in PostgreSQL.
6. A WebSocket broadcast notifies all connected Office UI clients.

The worker process remains suspended (holding the serialized graph checkpoint) until
it receives a resume signal from the Nexus API via Redis pub/sub.

## Approval Flow

```
1. Agent hits interrupt()
   |
   v
2. Nexus API creates ApprovalRequest (status: "pending")
   |
   v
3. WebSocket pushes {type: "approval_request", data: {...}} to Office UI
   |
   v
4. Alert icon (!) appears above the agent's avatar in the Phaser office
   |
   v
5. Tactician (user) walks their character to the agent's desk
   |
   v
6. Proximity trigger opens the Approval Modal
   - Shows: action type, reasoning, payload diff
   - Urgency indicator: low / medium / high / critical
   |
   v
7. Gamepad input:
   - A button = Approve
   - B button = Deny (with optional feedback via on-screen keyboard)
   |
   v
8. Office UI sends:
   - POST /api/v1/approvals/{id}/approve  (A pressed)
   - POST /api/v1/approvals/{id}/deny     (B pressed, with feedback body)
   |
   v
9. Nexus API updates ApprovalRequest status and broadcasts response via WebSocket
   |
   v
10. Worker receives resume signal:
    - Approved: LangGraph resumes from checkpoint, tool executes the action
    - Denied: LangGraph resumes with denial, agent logs feedback and moves on
```

## Gamepad Mapping

The Office UI maps standard gamepad inputs (HTML5 Gamepad API) to Tactician actions.

| Input | Action | Context |
|-------|--------|---------|
| Left Stick | Move Tactician | Always active |
| Right Stick | Pan Camera | Always active |
| A Button | Approve / Interact | When near agent with pending approval |
| B Button | Deny / Cancel | When approval modal is open |
| X Button | Inspect Agent | When near any agent |
| Y Button | Open Menu | Always active |
| D-Pad Up/Down | Scroll modal content | When approval modal is open |
| Start | Toggle dashboard overlay | Always active |
| LB/RB | Cycle between departments | When dashboard is open |

## ApprovalRequest Schema

Each approval request stored in the database contains:

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Unique request identifier |
| `agent_id` | UUID | The agent that triggered the interrupt |
| `action_category` | string | One of the ActionCategory enum values |
| `action_type` | string | Specific action (e.g., "git_push_to_main") |
| `payload` | JSON | Action-specific data (file paths, email body, etc.) |
| `diff` | text | Optional diff or preview of changes |
| `reasoning` | text | Agent's explanation of why this action is needed |
| `urgency` | string | low, medium, high, or critical |
| `status` | string | pending, approved, or denied |
| `feedback` | text | Tactician's feedback (populated on deny) |
| `created_at` | timestamp | When the interrupt was triggered |
| `responded_at` | timestamp | When the Tactician responded |

## WebSocket Message Types

The Office UI subscribes to approval events via WebSocket at
`ws://localhost:4300/api/v1/approvals/ws`.

### Approval Request (server to client)

```json
{
  "type": "approval_request",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "agent_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "action_category": "git_push",
    "action_type": "push_to_main",
    "payload": {"branch": "feat/payment-gateway", "commits": 3},
    "diff": "--- a/src/payments.py\n+++ b/src/payments.py\n...",
    "reasoning": "All tests pass. Ready to merge the payment gateway integration.",
    "urgency": "medium",
    "created_at": "2026-03-06T14:30:00Z"
  }
}
```

### Approval Response (server to client)

```json
{
  "type": "approval_response",
  "data": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "approved",
    "feedback": null,
    "responded_at": "2026-03-06T14:31:15Z"
  }
}
```
