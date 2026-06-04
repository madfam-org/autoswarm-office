# Secret Rotation Schedule - 2026Q3

| Field | Value |
|-------|-------|
| Status | SCHEDULED |
| Rotation window | 2026-07-07 14:00 America/Mexico_City |
| Namespace | selva |
| Targets | worker-api-token, consent-ledger-signing, colyseus-service |
| Runbook | [SECRET_ROTATION_POLICY.md](../SECRET_ROTATION_POLICY.md) |
| Dry-run command | `./scripts/rotate-secret.sh --all --namespace=selva --dry-run` |
| Execute command | `./scripts/rotate-secret.sh --all --namespace=selva` |
| Required env for consent ledger | `NEXUS_API_URL`, `NEXUS_ADMIN_TOKEN` |
| External calendar event | Operator must create/confirm outside the repo |
| Evidence after execution | Attach masked script output and any incident/follow-up links in this directory |

## Pre-window checklist

- [ ] Confirm external calendar event exists for the rotation window.
- [ ] Confirm primary and backup operator availability.
- [ ] Run the dry-run command from the operator workstation.
- [ ] Confirm `NEXUS_API_URL` and `NEXUS_ADMIN_TOKEN` are available for consent-ledger key promotion.
- [ ] Confirm cluster health and queue depth before execution.

## Post-window checklist

- [ ] Add an execution evidence file in this directory.
- [ ] Verify all deployments rolled and picked up the new values.
- [ ] Confirm `consent_ledger.key_promoted` audit event exists for consent-ledger rotation.
- [ ] File Enclii adapter gaps for any raw operation that should become first-class.
