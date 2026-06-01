# Karafiel contador G3 campaign proof pack

Status: approved proof pack for Tulana G3 evidence capture
Date: 2026-06-01
Campaign proof pack ID: `selva-proof-karafiel-contador-first-pesos-2026-06`
SKU: `karafiel__contador`
Tulana gate: `G3`
Campaign lane: `first_pesos_primary`

## Commercial objective

Prove the first direct paid peso path for the MADFAM ecosystem with a narrow,
high-intent campaign around Karafiel's contador tier.

This pack only approves campaign readiness. It does not approve CRM sending,
payment recognition, entitlement, payout, or revenue recognition.

## Offer

- Product: Karafiel
- Tier: Contador
- Public SKU key: `karafiel__contador`
- Price: MXN 1,299/month
- Buyer: independent accountants, boutique accounting practices, and fiscal
  operators who manage CFDI/tax workflows for Mexican SMBs.
- Motion: controlled pilot or warm outbound only.
- Primary CTA: start a paid Karafiel contador subscription through Dhanam.

## Target segment

Primary segment:

- Mexico-based accountants serving SMBs.
- Existing network/warm leads preferred.
- Buyers with recurring CFDI/fiscal operations pain.
- Exclude cold scraped contacts without consent provenance.

Disallowed segment:

- Purchased lead lists.
- Audiences with unclear consent.
- Regulated claims-sensitive audiences where the message could imply legal,
  accounting, or tax advice without human review.

## Approved claims

Allowed:

- Karafiel is positioned as a workflow/productivity layer for contador-facing
  fiscal operations.
- The campaign may reference the live monthly price of MXN 1,299 for the
  contador tier.
- The campaign may say this is a controlled commercial pilot while cash-GA
  evidence is being captured.
- The campaign may ask for a paid subscription or a short buying conversation.

Not allowed:

- Do not claim Karafiel replaces a certified accountant.
- Do not claim guaranteed SAT, CFDI, tax, legal, or compliance outcomes.
- Do not claim ecosystem-wide Commercial GA.
- Do not claim BBVA payout or recognized dashboard revenue until Tulana `G8`
  and `G9` pass.

## Message frame

Short-form outbound frame:

```text
Estamos abriendo un piloto pagado y controlado de Karafiel Contador para
despachos que manejan operaciones CFDI/fiscales recurrentes para PyMEs.
El plan Contador cuesta MXN 1,299/mes. Si te interesa, te paso el enlace de
pago y activamos el acceso con seguimiento humano.
```

Short-form inbound frame:

```text
Karafiel Contador está disponible como piloto comercial controlado por
MXN 1,299/mes. El flujo de pago se procesa vía Dhanam y la activación se
confirma con seguimiento humano.
```

## Risk review

| Risk | Control |
| --- | --- |
| Overclaiming tax/legal outcomes | Claims list prohibits guaranteed SAT, legal, tax, or compliance outcomes. |
| Premature GA claims | Copy says controlled commercial pilot, not GA. |
| Consent/compliance risk | PhyndCRM `G4` must pass before outbound send. |
| Payment/evidence gap | Dhanam `G5/G6` and Converge `G9` remain separate gates. |
| Entitlement gap | Karafiel `G7` must prove activation after payment. |

## Required downstream gates

- `G4`: PhyndCRM consent, suppression, and send approval.
- `G5`: Dhanam production checkout/session proof.
- `G6`: Dhanam payment and ledger proof.
- `G7`: Karafiel entitlement/webhook proof.
- `G8`: Dhanam/provider payout and BBVA arrival proof.
- `G9`: Converge approved revenue evidence.

## Tulana evidence record

This document is sufficient for Tulana `G3` because it contains:

- Campaign proof pack ID.
- Target segment.
- Offer and price.
- Approved/disallowed claims.
- Risk controls.
- Explicit downstream no-go gates.

Evidence locator:

`repo://selva-office/docs/KARAFIEL_CONTADOR_G3_CAMPAIGN_PROOF_PACK_2026-06.md`
