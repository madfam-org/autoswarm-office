# Audit Trail Gap Analysis (2026-05-04)

> Phase 3, item 19 in the [full-remediation plan](../ROADMAP.md). Read-only
> investigation: identifies every state-mutating endpoint in `apps/nexus-api/`
> that does NOT emit a corresponding `TaskEvent` row, ranked by impact.
> No code changes here — this is the implementation backlog for the
> follow-up audit-trail completeness PR.

## Summary

| Metric | Count |
|---|---|
| Routers audited | 38 |
| Routers with at least one mutation site | 20 |
| Total mutation sites (commit + flush) | 53 |
| Sites that emit a TaskEvent | 16 |
| **Gap sites (mutation without emit)** | **37** |
| N/A sites (intentional silent — internal counters / metrics) | 4 |

The 37 gap sites cluster across 14 routers. Five routers
(`workflows`, `marketplace`, `agents`, `tenants`, `maps`) account for
24 of the 37 gaps — those are where the implementation PR should
start.

---

## Per-router breakdown

### Routers that already emit (no action)
| Router | Mutations | Emits | Coverage |
|---|---:|---:|---|
| `stripe_webhooks.py` | 7 | 4 | ✅ 5/5 event handlers emit (the 2 non-emitting commits are tenant lookups) |
| `onboarding.py` | 2 | 3 | ✅ Voice-mode + tenant-identity changes emit |
| `invoices.py` | 2 | 2 | ✅ |
| `approvals.py` | 4 | 2 | ⚠ partial — see below |
| `swarms.py` | 5 | 2 | ⚠ partial — see below |
| `events.py` | 2 | 1 | N/A — events router itself shouldn't emit recursively |

### Routers with gaps (action needed)

| Router | Mutations | Emits | Suggested event types |
|---|---:|---:|---|
| `workflows.py` | 5 | 0 | `workflow.created`, `workflow.updated`, `workflow.deleted`, `workflow.imported` |
| `marketplace.py` | 5 | 0 | `marketplace.published`, `marketplace.installed`, `marketplace.rated`, `marketplace.deleted` |
| `agents.py` | 5 | 0 | `agent.created`, `agent.updated`, `agent.assigned`, `agent.deleted` (skip stats PATCH — N/A) |
| `tenants.py` | 4 | 0 | `tenant.created`, `tenant.config_updated`, `tenant.feature_flags_updated`, `tenant.limits_updated` |
| `maps.py` | 4 | 0 | `map.created`, `map.updated`, `map.deleted`, `map.imported` |
| `calendar.py` | 3 | 0 | `calendar.connected`, `calendar.disconnected`, `calendar.token_refreshed` |
| `schedules.py` | 2 | 0 | `schedule.created`, `schedule.deleted` |
| `hitl_confidence.py` | 2 | 0 | `hitl_confidence.config_updated` |
| `departments.py` | 2 | 0 | `department.created`, `department.updated` |
| `chat.py` | 1 | 0 | N/A — chat messages are already event-streamed via Colyseus + persisted as their own row |
| `artifacts.py` | 1 | 0 | `artifact.deleted` |
| `billing_internal.py` | 1 | 0 | N/A — token-record append is the audit trail itself |
| `command_approvals.py` | 1 | 0 | `command_approval.approved` / `command_approval.denied` |
| `tenant_identities.py` | 1 | 0 | `tenant.identity_updated` |

### Partial-emit routers (gaps within)

#### `swarms.py` — 5 mutations / 2 emits
| Function | Mutation | Status | Suggested event_type |
|---|---|---|---|
| `dispatch_task` | INSERT swarm_tasks | ✅ emits `task.dispatched` | — |
| `update_task_status` (PATCH) | UPDATE swarm_tasks | ❌ GAP | `task.status_changed` (carry old → new in payload) |
| `reap_stale_tasks` | UPDATE swarm_tasks bulk | ❌ GAP | `task.reaped_stale` (one event per reaped task or one summary) |
| `assign_agents_to_task` | UPDATE swarm_tasks.assigned_agent_ids | ❌ GAP | `task.agents_reassigned` |
| `delete_task` | DELETE swarm_tasks | ❌ GAP | `task.deleted` |

#### `approvals.py` — 4 mutations / 2 emits
| Function | Mutation | Status |
|---|---|---|
| `create_approval` | INSERT approval_requests | ✅ emits `approval.created` |
| `approve` | UPDATE approval_requests | ✅ emits `approval.approved` |
| `deny` | UPDATE approval_requests | ✅ emits `approval.denied` |
| `bulk_expire` | UPDATE approval_requests bulk | ❌ GAP — `approval.bulk_expired` |

---

## Top 12 highest-priority gaps

Ranked by which fix unlocks the most product, compliance, or
observability value. The implementation PR should land these first.

1. **`tenants.py:create_tenant` (line 296)** — `tenant.created` event.
   Org provisioning is the foundational audit event. Without it, every
   downstream "who provisioned this tenant and when" question is
   un-answerable from the event log. Compliance prerequisite for
   LFPDPPP audit (Mexican PII regulation requires creation timestamp
   + creator identity).

2. **`tenants.py:update_my_tenant` (line 470)** — `tenant.config_updated`.
   Locale / feature-flag / billing-tier changes ARE the tenant's own
   self-service knobs. Surfacing them as events lets the office UI
   show "Acme Corp changed their voice mode at 2026-05-04T03:14Z" in
   the activity feed.

3. **`swarms.py:update_task_status` (line ~735)** — `task.status_changed`.
   Worker writes back queued → running → completed/failed via this
   PATCH. Today the task table holds the truth but the event stream
   doesn't, so the OpsFeed UI re-polls the table instead of streaming
   events. Lattice cost: every `useTaskBoard` poll hits the DB.

4. **`workflows.py:create_workflow` + `update_workflow` + `delete_workflow`
   (lines 138, 300, 338)** — `workflow.{created,updated,deleted}`.
   Custom workflows are tenant intellectual property. Every change
   needs an audit row for "who reverted the prod workflow at
   2026-04-12 17:23 — was it us or the tenant?"

5. **`marketplace.py:publish_skill` (line 253)** — `marketplace.published`.
   Skill marketplace is platform-controlled inbound; publishes carry
   community trust. Operator needs an event stream to spot abuse
   patterns (one user publishing 50 skills in 10 minutes = automated
   spam).

6. **`marketplace.py:install_skill` (line 363)** — `marketplace.installed`.
   Mirrors the publish. Lets us answer "what skills did Tenant X
   install" without scanning their FS — load-bearing for the support
   triage workflow.

7. **`agents.py:create_agent` + `update_agent` + `delete_agent`
   (lines 178, 209, 295)** — `agent.{created,updated,deleted}`.
   Per-tenant agent roster changes. Customer-visible in the office UI
   sidebar; ops needs the event for "tenant complained their agent
   vanished — when did the delete happen?"

8. **`maps.py:create_map` + `update_map` + `delete_map`
   (lines 108, 169, 193)** — `map.{created,updated,deleted}`.
   Office layout is tenant content. Same audit-and-restore story as
   workflows.

9. **`calendar.py:connect_calendar` + `disconnect_calendar`
   (lines 179, 217)** — `calendar.{connected,disconnected}`.
   Compliance — when a tenant grants OAuth scope to read their gcal,
   the consent timestamp matters. Disconnect events also matter for
   "did they revoke before or after we sent the meeting reminder?"

10. **`schedules.py:create_schedule` + `delete_schedule`
    (lines 63, 113)** — `schedule.{created,deleted}`. Cron triggers
    that fire SwarmTasks. Without an event, the question "why did
    this task fire on 2026-04-30 at 09:00?" requires database
    archaeology.

11. **`tenant_identities.py:put_tenant_identity` (line 208)** —
    `tenant.identity_updated`. Outbound voice mode + From: header
    inputs. Already covered by the consent ledger for the
    voice-mode-change subset, but the broader identity change needs
    its own event for the office UI activity feed.

12. **`approvals.py:bulk_expire`** — `approval.bulk_expired`. Stale
    approvals get GC'd. Today the action is invisible; sometimes a
    customer asks "why didn't I get notified that approval X was
    auto-denied?" — answer requires the event stream to be complete.

---

## Implementation guidance

### The pattern to copy

`apps/nexus-api/nexus_api/routers/stripe_webhooks.py` is the canonical
reference. The late-import pattern avoids the
`approvals → events → approvals` circular import:

```python
async def some_endpoint(...):
    # ... mutation logic ...
    await db.commit()

    # Late import to avoid the events router → this router circular risk.
    # Mirror the pattern in approvals.py / swarms.py / onboarding.py.
    from .events import emit_event_db

    await emit_event_db(
        db,
        event_type="thing.happened",
        event_category="domain",
        org_id=current_user["org_id"],
        payload={
            "thing_id": str(thing.id),
            "previous_value": prev,
            "new_value": new,
            # NEVER include PII in payload — see helper docstring
        },
    )
    await db.commit()  # second commit for the event row
```

### Common pitfalls

1. **Don't include PII in `payload`** — events are returned by the
   `GET /api/v1/events` endpoint to ANY caller in the same org.
   Email addresses, names, phone numbers are out. Use IDs +
   reference-only (e.g., `tenant_id`, `agent_id`).

2. **Carry the org_id from `current_user`, not from the body** —
   tenant-scoping invariant per CLAUDE.md.

3. **Two commits is fine** — one for the mutation, one for the
   event. The second commit on the same session reuses the txn so
   it's cheap. If you really care about atomicity (the event must
   exist iff the mutation persisted), wrap both in a `begin_nested`
   savepoint.

4. **Don't fire events from inside `bulk_*` operations one-per-row**
   — emit one summary event with `{"affected_count": N, "ids": [...]}`
   in payload. Otherwise a 1000-row reap creates 1000 event rows
   and OpsFeed performance degrades.

### Test pattern

Mirror `apps/nexus-api/tests/test_stripe_webhook_handlers.py`:

```python
async def test_endpoint_emits_audit_event(db_session):
    await endpoint_under_test(...)

    rows = (await db_session.execute(
        select(TaskEvent).where(TaskEvent.org_id == "test-org")
    )).scalars().all()
    assert any(e.event_type == "thing.happened" for e in rows)
    event = next(e for e in rows if e.event_type == "thing.happened")
    assert event.payload["thing_id"] == "..."
    assert "email" not in event.payload  # no PII
```

---

## Phased rollout (suggested 3-week plan)

- **Week 1 — `tenants.py`, `swarms.py`, `agents.py`** (top-3 routers,
  10 gap sites, ~15 hr engineering). Unblocks the LFPDPPP compliance
  story and the OpsFeed-without-polling refactor.
- **Week 2 — `workflows.py`, `marketplace.py`, `maps.py`** (9 gap
  sites, ~12 hr). Tenant-content audit trail.
- **Week 3 — `calendar.py`, `schedules.py`, `hitl_confidence.py`,
  `departments.py`, `tenant_identities.py`, `artifacts.py`,
  `command_approvals.py`, `approvals.py:bulk_expire`** (long tail,
  ~10 gap sites, ~10 hr). Polish + close the gap completely.

Total estimated effort: ~37 hr engineering, parallelizable across 2-3
PRs since the routers don't share files.

## Compliance notes

- **LFPDPPP (Mexican PII)** requires a creation timestamp + creator
  identity for tenant accounts. Top-priority gap #1 (`tenant.created`)
  is the load-bearing fix.
- **GDPR Art. 30** requires a "record of processing activities" for
  the data controller. The TaskEvent table is our implementation; gaps
  here are gaps in our compliance posture.
- **Stripe live events** are already emitting (PR #116). Don't
  regress the pattern when refactoring.

## Followup (post-completeness)

Once the 37 gaps are closed:
- Consider replacing the manual `emit_event_db` discipline with
  Postgres CDC (Debezium → Kafka → audit topic) per Phase 3 item 23
  in the remediation plan. CDC eliminates the "did the engineer
  remember to emit?" failure mode entirely — schema mutations
  become events automatically.
