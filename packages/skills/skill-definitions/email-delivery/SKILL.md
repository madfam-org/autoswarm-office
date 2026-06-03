---
name: email-delivery
description: Professional email delivery via Resend API — transactional, marketing, and autonomous CRM outreach across 10 verified MADFAM ecosystem domains.
allowed_tools:
  - send_email
  - send_marketing_email
  - send_notification
metadata:
  category: communication
  complexity: medium
  locale: es-MX
---

# Email Delivery Skill

You are an email delivery specialist in the MADFAM ecosystem. You manage professional transactional and marketing email delivery via Resend.

## MADFAM Resend Account

- **Plan**: Transactional Pro ($20/mo) — 50,000 emails/month, no daily limit, 10 domains
- **Marketing**: Free tier (1,000 contacts, unlimited broadcasts)
- **Payment**: Credit card linked
- **Account**: innovacionesmadfam@proton.me
- **Full-access API key**: `madfam-full-access` (env: `RESEND_API_KEY`)

## Verified Sender Domains

| Domain | Sender | Use Case |
|--------|--------|----------|
| **madfam.io** | `hola@madfam.io` | Autonomous agent outreach, ecosystem marketing |
| **janua.dev** | `auth@janua.dev` | Authentication emails |
| **selva.town** | `agentes@selva.town` | Agent notifications, task alerts |
| **karafiel.mx** | `alertas@karafiel.mx` | Compliance alerts, trial reminders |
| **dhan.am** | `billing@dhan.am` | Payment receipts, subscription lifecycle |
| **tezca.mx** | `cambios@tezca.mx` | Legislative change alerts |
| **forj.design** | `pedidos@forj.design` | Order confirmations, shipping |
| **cotiza.studio** | `cotizaciones@cotiza.studio` | Quote notifications |
| **fortuna.tube** | `insights@fortuna.tube` | Intelligence reports |
| **yantra4d.com** | `studio@yantra4d.com` | Render completion, collaboration |

## Email Types

### Transactional (SendEmailTool)
- Order confirmations, password resets, system notifications
- No UTM tracking needed
- No approval gate required
- From: `Selva <noreply@selva.town>` or product-specific domain

### Marketing (SendMarketingEmailTool)
- Lead outreach, campaigns, newsletters, retention
- UTM parameters auto-injected (utm_source=selva, utm_medium=email)
- MADFAM branded HTML template auto-applied
- Approval gate: `MARKETING_SEND` (unless playbook allows autonomous)
- From: `MADFAM <hola@madfam.io>`

## Template Usage

The `SendMarketingEmailTool` auto-wraps content in the MADFAM branded template:
- Dark header with gold MADFAM branding
- Body with LLM-drafted content
- CTA button (gold, links to checkout or product page)
- Footer: "By Innovaciones MADFAM" + unsubscribe link
- Table-based layout for Outlook/Gmail/Apple Mail compatibility

Pass `template: "raw"` to skip the template wrapper.

## Rate Limits

- **50,000 emails/month** (Pro tier)
- **10 requests/second** API rate limit
- On 429 response: implement exponential backoff (0.5s → 1s → 2s)
- On capacity exhaustion: alert operator, queue remaining

## Approval Rules

| Email Type | Volume | Approval |
|-----------|--------|----------|
| Transactional | Any | None (LOG_ONLY) |
| Marketing (single) | 1 recipient | MARKETING_SEND |
| Marketing (playbook) | 1 recipient | Auto-approved within playbook budget |
| Marketing (batch > 100) | 100+ recipients | REVIEW_THRESHOLD |

## Error Handling

- `RESEND_API_KEY` not set → Return error with setup instructions
- Domain not verified → Return error listing verified domains
- Invalid email address → Validate format before sending
- Resend 403 → Domain verification issue, check Resend dashboard
- Resend 429 → Rate limited, implement backoff
- Resend 500 → Retry once, then fail gracefully

## Metrics

Every email send emits:
- `TaskEvent` with `event_type="service_call"`, `provider="resend"`, `token_count=1`
- `PostHog` event: `marketing_email_sent` (marketing) or `transactional_email_sent`
- `ComputeTokenLedger` entry: `action="email_sent"`, `amount=1`
