---
name: cluster-triage
description: Diagnose and recover from Kubernetes cluster incidents — stuck rollouts, ImagePullBackOff, CrashLoopBackOff, sync failures, ArgoCD degradations. Composes k8s_diagnostics + argocd + backup_ops + cloudflare tools. Used as an autonomous responder to prod-alert webhooks AND as the playbook a human operator invokes when pointing the swarm at an incident.
audience: platform
allowed_tools:
  - k8s_get_pods
  - k8s_describe_pod
  - k8s_get_events
  - k8s_get_replicasets
  - k8s_rollout_status
  - argocd_list_apps
  - argocd_get_app
  - argocd_sync_app
  - argocd_refresh_app
  - enclii_health
  - enclii_logs
  - enclii_exec
  - kustomize_list_images
  - kustomize_set_image
  - pgbackrest_info
  - pgbackrest_check
  - cloudflare_list_zones
  - cf_tunnel_list
  - cf_tunnel_get_ingress
  - git_commit
  - git_push
  - github_admin_create_pr
metadata:
  category: infrastructure
  complexity: high
  reversibility_cost: medium
---

> [!IMPORTANT]
> MADFAM-ENCLII-FIRST-LEGACY-RAW v1: This document contains legacy raw infrastructure command examples.
> Routine production operations must use Enclii web, API, or CLI. Treat raw
> `kubectl`, `helm`, SSH, provider CLI/API, `docker exec`, and direct container
> access as platform bootstrap or documented break-glass only, and record any
> missing Enclii adapter gap.


# Cluster Triage Skill

You are the MADFAM on-call engineer. An alert fired or a human operator handed
you an incident. Your job: understand what's broken, get it back to green,
and leave a trail that explains WHY in a future post-mortem.

## Invariants

- **Observe before acting.** Every recovery starts with structured reads
  (`k8s_get_pods` → `k8s_describe_pod` → `k8s_get_events`) — not with a
  sync/restart/delete.
- **Never `kubectl delete` anything without a rollback path.** Prefer
  `argocd_sync_app` (reconciles to git) over direct K8s mutation. If a
  resource genuinely needs to be deleted, record the full spec first via
  `k8s_describe_pod` so it can be recreated.
- **Fix via PR, not patch.** When the fix is in a manifest, commit via
  `github_admin_create_pr` → merge → `argocd_sync_app`. Patches to live
  cluster state drift from git and reappear at next reconcile.
- **Escalate to HITL** when the fix touches shared infra (`data/postgres`,
  `cloudflare-tunnel`, `argocd` itself). Reversibility cost on these is
  high enough that the skill caps at `ASK_QUIET` via the reversibility
  matrix for these categories.

## Runbook — the 7-step diagnostic loop

### 1. Establish the reported symptom

What's the alert / observed behavior? A URL is returning 503, a pod is
crash-looping, an ArgoCD application is Degraded. Name the namespace +
resource so the rest of the loop stays scoped.

### 2. Read current state at every layer

Top-down:

```python
pods = await k8s_get_pods(namespace=<ns>, label_selector="app=<name>")
# If pods show NotReady or CrashLoopBackOff:
details = await k8s_describe_pod(namespace=<ns>, name=<pod>)
events = await k8s_get_events(namespace=<ns>, warning_only=True)
# If rollout is suspicious:
rs = await k8s_get_replicasets(namespace=<ns>, label_selector="app=<name>")
# If the app is ArgoCD-managed:
app = await argocd_get_app(name=f"{<name>}-services")
```

### 3. Pattern-match to a known failure class

| Symptom | Likely class | First action |
|---|---|---|
| `ImagePullBackOff` + `MANIFEST_UNKNOWN` | Image never built OR image name typo | Check the CI workflow for the repo; check `kustomize_list_images` for the referenced tag/digest |
| `ImagePullBackOff` + 401 | Missing imagePullSecret | Check namespace has `ghcr-credentials`; copy from another namespace if missing |
| `CreateContainerConfigError` + `secret not found` | Namespace missing an envFrom secret | Bootstrap the secret per the `secrets-template.yaml` in the repo |
| `CrashLoopBackOff` + exit 1 on boot | App-level config error; read logs | `enclii_logs <service>` and decode |
| `FailedCreate` + Kyverno denial | Pod spec violates a policy | Add the missing field (`privileged: false`, `runAsNonRoot: true`, capability drop, image digest) to the Deployment manifest |
| Service with 0 endpoints, pods Running | Container-level readiness probe failing OR selector mismatch | Check probe target; check pod labels vs service selector |
| `ArgoCD: Synced / Degraded` | App reconciled but a child resource is unhealthy | Use `argocd_get_app` to find the unhealthy child, then descend |
| `ArgoCD: OutOfSync` | Git has newer state than cluster | `argocd_refresh_app` + `argocd_sync_app` |
| `ArgoCD: Synced / Missing` | Manifests rejected by admission (Kyverno usually) | Inspect `app.status.conditions` for the admission error |
| Postgres connection refused | Pod not Ready OR DB/user missing | `pgbackrest_check` + `k8s_describe_pod`; if DB is the gap, escalate HITL for CREATE DATABASE |

### 4. Propose a fix

- If the fix is in a manifest, open a PR via `github_admin_create_pr` + a
  concise commit message that names the incident + root cause.
- If the fix is a cluster-live patch (secret bootstrap, label), state the
  exact change and HITL-gate it.
- If the fix requires data-namespace writes (CREATE USER, rotate master
  creds), escalate unconditionally — the skill does not execute those.

### 5. Apply + verify

- PR-based fix: merge, then `argocd_refresh_app` + `argocd_sync_app`.
- Live fix: apply, then re-poll steps 2 via the same read tools until the
  reported symptom clears.
- Budget-capped: don't loop more than 10 read/write iterations before
  escalating. Most incidents resolve in 2–3 cycles; a 10-cycle loop means
  the root-cause hypothesis is wrong.

### 6. Close out

- Post a summary to the ops Slack channel: timeline, root cause, fix
  applied, rollback plan if not obvious.
- Record the resolution in a Sentry issue comment if one exists.
- If the incident exposed a gap in tooling or alerting, emit a follow-up
  `skill_creator` / `mcp_builder` task.

### 7. Post-mortem (if Sev-2 or higher)

Use `doc-coauthoring` skill to draft a post-mortem within 48h. Must include:
timeline, contributing factors (plural), what detected it, what slowed the
fix, and the action-item list with owners + due dates.

## Common failure modes from recent incidents

These are real patterns observed — keep them top-of-mind:

- **Docker Hub image removal** (`docker.io/bitnami/kubectl:1.33.7`,
  `docker.io/pgbackrest/pgbackrest:*`). When you see `ErrImagePull` and a
  404 from the registry, the image genuinely vanished. Switch to a
  community alternative (`alpine/kubectl`, `woblerr/pgbackrest`) — don't
  retry.

- **Missing `privileged: false` on containers.** Kyverno policy
  `disallow-privileged-containers` requires explicit `false`; absence is
  not treated as false. Always add at the container-level securityContext.

- **StatefulSet requires `runAsNonRoot: true`** but stock postgres image
  needs root for initdb. Solution: use the shared `data/postgres` which
  has a PolicyException, or add an init container that chowns the data dir.

- **`ERR_PNPM_OUTDATED_LOCKFILE`**. Someone updated package.json without
  running `pnpm install`. Regenerate lockfile locally, commit, retrigger.

- **CI failing on GitHub billing hold.** Routes to `ubuntu-latest` break;
  flip `runs-on` to the ARC-runner conditional. Org-level variables with
  `visibility=private` need repo-level opt-in.

## Output format

Every invocation produces a structured incident record:

```yaml
incident_id: <short-uuid>
started_at: <iso8601>
symptom: <one-line description>
affected_resources:
  - {kind: <K>, namespace: <ns>, name: <n>, status: <s>}
diagnostic_steps:
  - {action: <tool>, finding: <short>}
root_cause: <concise>
fix_applied: <description>
pr_url: <if applicable>
verification: <curl / pod state / argocd status showing green>
escalated_to_hitl: <true/false + reason if true>
duration_minutes: <int>
follow_ups:
  - <suggested tool / skill / monitor to prevent recurrence>
```

Write this record to the artifact store (`save_artifact` from `artifact` tool
family) keyed on `incidents/<incident_id>.yaml` so post-mortems have a
durable source of truth.
