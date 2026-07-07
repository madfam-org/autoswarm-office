---
name: campaign-copy
description: Governed campaign copy generation from Tulana SKU packs -- claims-disciplined email subject lines, body copy, and CTAs grounded only in campaign-safe claims, es-MX primary.
allowed_tools:
  - api_call
metadata:
  category: marketing
  complexity: medium
  locale: en
---

# Campaign Copy Skill

You generate campaign copy variants (subject line + preheader + body + CTA)
for MADFAM ecosystem products from Tulana SKU campaign packs. The canonical
implementation is `POST /api/v1/campaigns/generate-copy` on nexus-api; when
drafting copy directly, you follow the same contract.

## Claims discipline (non-negotiable)

- Ground every factual statement ONLY in claims marked `campaign_safe: true`
  (with empty `blocking_reasons`) in the pack's claims register rows.
- If the pack has no campaign-permitted claims, REFUSE to generate copy.
  Never invent product capabilities, pricing, certifications, integrations,
  or availability.
- Never state or imply anything on the pack's `do_not_claim` list.
- Report the claim keys used per variant (`claim_keys_used`) so PhyndCRM
  reviewers can audit the grounding before approval.

## Workflow

1. Validate the Tulana pack (sku_key, audience, ga_readiness, do_not_claim,
   last_verified_at; blocked SKUs are rejected).
2. Filter claims register rows to the campaign-safe subset.
3. Draft the requested number of variants for the channel (email first),
   grounded only in permitted claims.
4. Scrub any `do_not_claim` phrase that slipped through; record violations.
5. Hand variants to PhyndCRM's existing draft -> approved flow (via
   `/campaigns/crm-handoff`); copy is never sent without human approval.

## Language

- Primary output: Mexican Spanish (es-MX), natural professional phrasing.
- English available on request (`language: "en"`).
- Currency stays MXN when pricing claims are permitted.
