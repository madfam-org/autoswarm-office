---
name: vault-break-glass
description: Recover MADFAM Vault custody, rebootstrap Vault when recovery material is unavailable, restore ExternalSecrets, and rotate provider credentials without exposing secret values to agents or logs.
audience: platform
allowed_tools:
  - k8s_get_pods
  - k8s_describe_pod
  - k8s_get_events
  - k8s_rollout_status
  - argocd_get_app
  - argocd_sync_app
  - argocd_refresh_app
  - selva_vault_list
  - write_kubernetes_secret
  - enclii_health
  - enclii_logs
  - save_artifact
metadata:
  category: security
  complexity: high
  reversibility_cost: high
---

# Vault Break-Glass Skill

You are operating inside the MADFAM platform slice of Selva. This skill is for
Vault custody recovery, ExternalSecrets restoration, and credential rotation.
It must never be available to tenant swarms.

## Invariants

- Do not print, summarize, or store raw secret values in task output, logs,
  artifacts, Git commits, comments, or chat.
- Treat missing Vault root/admin tokens and missing unseal/recovery shares as a
  custody failure. Do not claim the existing Vault can be administratively
  recovered unless a valid token or threshold key material exists.
- Bitwarden is the admin custody backup. Vault is the operational source of
  truth for Kubernetes workloads.
- Rebootstrap requires a human/admin custody checkpoint before proceeding past
  `vault operator init`, because the new unseal shares and initial root token
  must be saved outside the cluster immediately.
- Selva agents may help with inventory, validation, and orchestration. Agents
  must not hold reusable root tokens or unseal shares.

## Recovery Decision Tree

1. Check Vault state without printing secrets:
   - Vault pod Ready?
   - initialized?
   - sealed?
   - `vault-store` Ready?
   - ExternalSecrets Ready?
2. If a valid admin/operator Vault token exists, use the approved repair
   script path and do not rebootstrap.
3. If no valid token exists but threshold unseal/recovery shares exist,
   generate a short-lived root token using Vault's root-token generation flow.
4. If no valid token and no threshold key material exists, stop treating the
   current Vault as recoverable. Plan a controlled rebootstrap and provider
   rotation.

## Rebootstrap Sequence

1. Freeze secret-writing automation and pause nonessential rotations.
2. Record a preflight artifact with:
   - current Argo app health
   - `vault-store` condition
   - affected ExternalSecrets by namespace/name
   - current public status result
3. Destroy only the old Vault data path after explicit human approval.
4. Let GitOps recreate Vault.
5. Initialize Vault with Shamir 5-of-3.
6. Immediately save custody material:
   - `MADFAM Vault Break-Glass Access`
   - `MADFAM Vault Unseal Share 1 of 5`
   - `MADFAM Vault Unseal Share 2 of 5`
   - `MADFAM Vault Unseal Share 3 of 5`
   - `MADFAM Vault Unseal Share 4 of 5`
   - `MADFAM Vault Unseal Share 5 of 5`
   - `MADFAM Vault Initial Root Token - TEMPORARY`
7. Unseal Vault with any 3 shares.
8. Enable audit devices before writing secrets.
9. Enable KV v2 at `secret/`.
10. Configure Kubernetes auth and the `eso-reader` role for ExternalSecrets.
11. Configure the Selva writer role only for the MADFAM path.
12. Rotate or recreate provider credentials, write them into Vault, and resync
    ExternalSecrets.
13. Revoke temporary root/admin tokens after validation.

## Selva Access Boundary

Only the MADFAM platform org may activate this skill. The platform org is
resolved by `PLATFORM_ORG_ID`; if it is unset, the safe default is that no org
is platform. Production must run with `AUDIENCE_FILTER_ENABLED=true`.

Vault-side policy for Selva must be path-scoped to MADFAM-owned paths, not the
entire `secret/` tree. Recommended path:

```hcl
path "secret/data/madfam/*" {
  capabilities = ["create", "update", "patch"]
}

path "secret/metadata/madfam/*" {
  capabilities = ["read", "list"]
}
```

Do not give Selva a policy that can read customer tenant secrets or global
provider credentials unless a separate RFC and HITL approval covers that path.

## Output Artifact

Every invocation must write a non-secret artifact:

```yaml
recovery_id: <timestamp-short-uuid>
started_at: <iso8601>
vault_state:
  initialized: <true|false>
  sealed: <true|false>
  store_ready: <true|false>
decision: <repair_existing|generate_root|rebootstrap>
custody:
  bitwarden_items_created:
    - MADFAM Vault Break-Glass Access
  unseal_strategy: Shamir 5-of-3
external_secrets:
  affected_count: <int>
  ready_after: <true|false>
rotations:
  completed:
    - <provider-or-secret-class>
  pending:
    - <provider-or-secret-class>
verification:
  argocd_healthy: <true|false>
  status_operational: <true|false>
follow_ups:
  - <action>
```
