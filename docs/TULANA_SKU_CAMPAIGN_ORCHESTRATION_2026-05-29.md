# Tulana SKU campaign orchestration

Date: 2026-05-29

Status: **Program Phase 2** — implementation contract for
[Autonomous Operations Program § Phase 2](./AUTONOMOUS_OPERATIONS_PROGRAM.md#phase-2--campaign-planning--execution-4-6-weeks)

## Direct surfaces

| Surface | URL |
| --- | --- |
| Selva office UI | `https://selva.town` |
| Selva API | `https://api.selva.town` |
| Selva websocket | `wss://ws.selva.town` |
| Tulana dashboard | `https://tulana-app.madfam.io/dashboard` |
| Phynd CRM MADFAM tenant | `https://crm.madfam.io` |

## Role boundary

Selva orchestrates campaign work after Tulana produces evidence. Selva must not
invent product claims, override Tulana readiness, or treat a waived blocker as
high-confidence GA.

Tulana owns:

- SKU readiness;
- comparator and crawler evidence;
- cost basis;
- WTP/PMF facts;
- approved/waived/blocker states;
- campaign-ready export.

Selva owns:

- agent assignment;
- task planning;
- draft generation;
- human-in-the-loop approvals;
- campaign maintenance;
- feedback loops from CRM outcomes back into Tulana.

Phynd CRM owns:

- contact and audience records;
- campaign staging and send/review flows;
- engagement events;
- unsubscribe/consent state.

## Input contract from Tulana

Selva should consume either an API endpoint or export with this minimum shape:

```json
{
  "generated_at": "2026-05-29T00:00:00Z",
  "sku_key": "avala__issuer",
  "platform": "avala",
  "audience": "credential issuers",
  "ga_readiness": "near_ready",
  "rank": 1,
  "readiness_reasons": ["comparator_ready", "cost_waived", "wtp_pending"],
  "value_prop": "Evidence-backed positioning text",
  "proof_points": [
    {
      "label": "Required adjacent comparator",
      "source": "Canvas Credentials",
      "url": "https://www.instructure.com/canvas/credentials"
    }
  ],
  "do_not_claim": ["Do not claim external legal approval"],
  "policy_state": "waived_by_operator",
  "last_verified_at": "2026-05-29T00:00:00Z"
}
```

Selva should reject campaign tasks that lack:

- SKU key;
- audience;
- readiness state;
- at least one proof point or explicit waiver;
- `do_not_claim` guardrails;
- verification timestamp.

## Selva import API

`POST /api/v1/campaigns/import-tulana-pack` — validates packs, returns ranked
accept/reject lists, optional `dispatch_tasks` to enqueue `sku_campaign_planning`
tasks on the `intelligence` graph.

## Agent workflow

1. Import Tulana SKU campaign pack.
2. Rank SKUs by closest-to-GA and commercial attractiveness.
3. Create one Selva task per SKU/audience/campaign lane.
4. Generate draft text variants from Tulana proof points only.
5. Send drafts to human approval when campaign action is classified as `ask`.
6. Hand approved drafts to Phynd CRM.
7. Monitor engagement events.
8. Write outcome summaries back to Tulana as buyer-signal evidence.

## Required guardrails

- Do not campaign on `blocked` SKUs unless the campaign is explicitly a waitlist
  or discovery campaign.
- Label waived SKUs as waived internally; do not call them externally validated.
- Do not mention Tezca as a legal reviewer.
- Do not claim pricing, availability, or compliance certifications without a
  Tulana proof point.
- Preserve unsubscribe and consent state from Phynd CRM.
- Route campaign send actions through human approval until the permission matrix
  explicitly allows autonomous sends for that lane.

## Suggested Selva task categories

| Category | Purpose |
| --- | --- |
| `sku_campaign_planning` | Rank and plan campaign lanes from Tulana export |
| `campaign_draft` | Produce text variants for one SKU/audience |
| `crm_campaign_handoff` | Send approved assets to Phynd CRM |
| `campaign_result_review` | Summarize outcomes and buyer-signal evidence |
| `tulana_feedback_update` | Push validated campaign outcomes back to Tulana |

## Tests and acceptance

- Contract test for Tulana import schema.
- Guardrail test that `do_not_claim` content is excluded from generated copy.
- HITL test for outbound campaign approval.
- Phynd CRM handoff test with idempotency key.
- Feedback-loop test that campaign outcomes become Tulana buyer-signal evidence.

Definition of done:

- Selva can import a Tulana campaign pack.
- Agents generate drafts using only source-backed proof points.
- Human approval gates outbound campaign actions.
- Phynd CRM receives traceable campaign payloads.
- Tulana receives engagement outcomes as evidence, not free-form anecdotes.
