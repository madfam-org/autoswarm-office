---
name: tenant-onboarding
description: Bootstrap a brand-new MADFAM tenant end-to-end across every service the platform owns state in — Janua (auth), Dhanam (billing), PhyndCRM (ops), Karafiel (Mexican fiscal), Resend (email), Selva Office (workers), plus the central tenant_identities record. A single skill invocation advances a tenant from "signed contract" to "agents can operate on their behalf", with HITL gates on the two irreversible steps (SAT cert upload + DNS record publication). Use on every new tenant; never hand-assemble the primitives.
audience: platform
allowed_tools:
  - janua_oauth_client_create
  - janua_oauth_client_rotate_secret
  - janua_org_create
  - dhanam_space_create
  - dhanam_subscription_create
  - dhanam_credit_ledger_query
  - phyndcrm_tenant_create
  - phyndcrm_pipeline_bootstrap
  - phyndcrm_tenant_config_get
  - karafiel_org_create
  - karafiel_sat_cert_upload
  - karafiel_pac_register
  - karafiel_invoice_series_create
  - resend_domain_add
  - resend_domain_verify
  - resend_domain_list
  - tenant_create_identity_record
  - tenant_resolve
  - tenant_validate_consistency
  - save_artifact
metadata:
  category: tenancy
  complexity: high
  reversibility_cost: high
  max_tier: ASK_QUIET
---

# Tenant Onboarding Skill

You are seeding a new tenant across the MADFAM ecosystem. Every primitive
call is idempotent on its own, but the sequencing matters: downstream
services expect upstream IDs, and the central `tenant_identities` record
must land last so offboarding + drift-check tooling has a complete map.

## Invariants

- **Canonical ID = Janua org_id.** Every service keys its tenant record
  off this value. Do not invent alternative IDs.
- **SAT cert upload is HITL.** `karafiel_sat_cert_upload` transmits the
  tenant's CFDI signing private key — it's the legal equivalent of a
  rubber stamp. ALWAYS require human sign-off from a legal representative
  before calling.
- **DNS record publication is HITL.** The DNS records returned by
  `resend_domain_add` must be published on the tenant's DNS by the
  tenant — surface them, don't try to auto-publish. Only
  `resend_domain_verify` runs unattended once the tenant confirms.
- **Identity record lands LAST.** `tenant_create_identity_record` is the
  checkpoint that marks onboarding complete. Calling it before a service
  returned its ID leaves the row with NULLs and reconciliation becomes
  lossy.
- **Mexican fiscal (Karafiel) only if invoicing inside Mexico.** If the
  tenant isn't billing in MXN, skip steps 6–8. Record in metadata that
  they're outside Mexican fiscal perimeter.

## Budget expectation

This is a ~8–15 minute end-to-end run with 3–4 HITL pauses. If it
completes in under 3 minutes, you skipped something; if it's past 30
minutes, something is stuck and should escalate.

## Required inputs

Before invocation, you should already have:

- `legal_name`, `primary_contact_email`, `canonical_id` (use Janua
  org_id once created)
- `voice_mode` selection (see `outbound-voice` skill — one of
  `user_direct` / `dyad_selva_plus_user` / `agent_identified`)
- If Mexican-fiscal: `rfc`, `razon_social`, `regimen_fiscal` (SAT code
  e.g. `601`), `domicilio_fiscal_cp`
- If bring-your-own-domain: the tenant's sending domain (e.g.
  `tenant.com`)

Missing any of these → DO NOT start. Surface a structured requirements
gap back to the caller instead.

## Canonical 12-step flow

### 1. Janua org + OAuth client

```python
org = await janua_org_create(
    legal_name=..., primary_contact_email=..., domain=...
)
# org.org_id is now the canonical_id for every downstream step.

oauth = await janua_oauth_client_create(
    org_id=org.org_id,
    name=f"{slug}-worker",
    scopes=["read:self", "write:self"],
    redirect_uris=[...],
)
# Capture oauth.client_secret — do NOT log it. Store in Vault below.
```

### 2. Dhanam space + free-tier subscription

```python
space = await dhanam_space_create(
    canonical_id=org.org_id, legal_name=..., primary_contact_email=...
)
sub = await dhanam_subscription_create(
    space_id=space.id, plan="free", credits_initial=0
)
```

### 3. PhyndCRM tenant_config + default pipeline

```python
await phyndcrm_tenant_create(
    tenant_id=org.org_id,
    legal_name=...,
    primary_contact_email=...,
    voice_mode=<selected-voice-mode>,
)
await phyndcrm_pipeline_bootstrap(tenant_id=org.org_id)
# The default 6-stage pipeline is fine for 99% of tenants; override only
# if the tenant explicitly requested a custom pipeline pre-signing.
```

### 4. Resend domain (only if bring-your-own-domain)

```python
domain = await resend_domain_add(name=tenant_domain, region="us-east-1")
# domain.records is the full list of DNS records the tenant must publish.
# ⚠️ HITL GATE — surface these records to the tenant and wait for
# confirmation that they're published. Do NOT continue until then.
```

### 5. Resend domain verify

```python
status = await resend_domain_verify(domain_id=domain.id)
# Retry every 5 minutes for up to 2 hours. If not verified after 2h,
# escalate — the records likely have a typo.
```

### 6. Karafiel org (Mexican fiscal only)

```python
k_org = await karafiel_org_create(
    rfc=..., razon_social=..., regimen_fiscal=...,
    domicilio_fiscal_cp=..., correo_contacto=primary_contact_email,
)
```

### 7. Karafiel SAT cert upload ⚠️ HARD HITL

```python
# ⚠️ HITL GATE — DO NOT call this without:
# - Legal representative of the tenant confirming the .cer and .key
# - Password confirmed via out-of-band channel (NOT email)
# - Written authorization logged in the artifact store
await karafiel_sat_cert_upload(
    org_id=k_org.org_id,
    cer_base64=..., key_base64=..., key_password=...,
)
```

If the legal representative has NOT confirmed, stop here. Emit a
follow-up task with the org partial state and a required action.

### 8. Karafiel PAC registration + invoice series

```python
await karafiel_pac_register(org_id=k_org.org_id)
await karafiel_invoice_series_create(
    org_id=k_org.org_id, serie="A", folio_start=1
)
```

### 9. Selva Office seat (if tenant users will join the office UI)

This is typically provisioned per-user rather than per-tenant, but if
the tenant signed for N seats pre-launch, create them now via the seat
provisioning tools (not covered by Phase 2 primitives — see
`selva_office_provisioning.py` when it lands, or HITL-defer).

### 10. Central identity record

```python
await tenant_create_identity_record(
    canonical_id=org.org_id,
    legal_name=...,
    primary_contact_email=...,
    janua_org_id=org.org_id,
    dhanam_space_id=space.id,
    phyndcrm_tenant_id=org.org_id,
    karafiel_org_id=k_org.org_id if mexican_fiscal else None,
    resend_domain_ids=[domain.id] if byo_domain else [],
    metadata={
        "onboarded_at": <iso8601>,
        "onboarded_by": <agent-id-or-operator-email>,
        "voice_mode": <voice_mode>,
        "plan": "free",
    },
)
```

### 11. Consistency check

```python
result = await tenant_validate_consistency(canonical_id=org.org_id)
# result.drifts must be empty. If not, the onboarding did NOT succeed —
# some service rejected state silently. Escalate.
```

### 12. Record artifact + close

```python
await save_artifact(
    key=f"tenants/{org.org_id}/onboarding.yaml",
    content=<the structured record below>,
)
```

Output structure:

```yaml
canonical_id: <janua-org-id>
legal_name: <name>
onboarded_at: <iso8601>
onboarded_by: <agent-or-operator>
plan: free
voice_mode: <mode>
services:
  janua: {org_id, oauth_client_id}
  dhanam: {space_id, subscription_id}
  phyndcrm: {tenant_id, pipeline_id}
  karafiel: {org_id, sat_cert_fingerprint, pac_status, serie}  # if MX
  resend: {domain_id, verification_status}  # if BYOD
hitl_approvals:
  - {step: resend_dns_publication, approver, approved_at}
  - {step: sat_cert_upload, approver, approved_at}  # if MX
identity_record_id: <uuid>
drift_check: {services_checked, drifts}
```

## Recovery from partial failure

Onboarding is only "done" when every step's ID is in the identity
record. If step N fails:

- **Steps 1–3** fail: the tenant has no canonical identity yet. Safe to
  retry from step 1 with a NEW slug — the old partial state is harmless
  (Janua client without org pointing at nothing).
- **Steps 4–5** fail: Resend domain exists but unverified. Do NOT
  delete + recreate (that burns the DNS records the tenant already
  published). Debug the DNS records directly.
- **Steps 6–8** fail: Karafiel state is partially set. The safest
  recovery is to continue from the failing step — do NOT delete the
  partial Karafiel org; that would orphan any PAC registration.
- **Step 10** fail (identity record): ALL service state exists but
  there's no central map. Manually invoke `tenant_create_identity_record`
  with the IDs gathered from the previous steps. This is the one step
  that's safe to retry on its own.
- **Step 11** fail (drift): one service lost state. Re-run the
  service's bootstrap step idempotently; most primitive tools treat
  "already exists" as success.

## HITL decision cheat sheet

| Step | HITL? | Why |
|---|---|---|
| 1 (Janua org) | ALLOW | Reversible — orgs can be soft-deleted |
| 2 (Dhanam space) | ALLOW | Reversible |
| 3 (PhyndCRM tenant) | ALLOW | Reversible |
| 4 (Resend domain add) | ALLOW (but surface records before step 5) | DNS records visible; no send happens yet |
| 5 (Resend domain verify) | ALLOW | Polling; no mutation |
| 6 (Karafiel org) | ALLOW | Reversible; no fiscal writes yet |
| 7 (SAT cert upload) | **ASK_DUAL** | Tenant's CFDI signing key — requires legal rep sign-off |
| 8 (PAC register) | ASK | Registers tenant with SAT via PAC — harder to reverse |
| 9 (Office seats) | ALLOW | Reversible per-seat |
| 10 (identity record) | ALLOW | Pure record-keeping |
| 11 (consistency check) | ALLOW | Pure read |
| 12 (artifact save) | ALLOW | Pure record-keeping |

## Don'ts

- Don't skip step 11 (consistency check). It's the only mechanism that
  catches a silent service failure.
- Don't log `oauth.client_secret` or SAT cert bytes. Use Vault for the
  OAuth secret; treat cert bytes as write-once-to-Karafiel, never held
  in agent memory.
- Don't parallelize the steps. Dhanam references Janua org_id; PhyndCRM
  references Janua org_id; identity record references every one. A
  parallel launch will race and leave partial state.
