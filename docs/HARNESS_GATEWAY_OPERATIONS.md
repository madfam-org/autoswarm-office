# Harness Integration — Operations Runbook

This document is the **single source of truth** for all remaining operational steps required to bring both phases of the Harness Agent parity integration into production. All code changes are already merged to `main` — what follows is exclusively infrastructure provisioning, secret management, and platform registration.

> [!IMPORTANT]
> Complete steps **1 → 9** in order on a fresh deployment. On a re-deploy (e.g., upgrading from an older revision), only re-run steps that introduce new resources.

---

## 1. Apply Kubernetes Infrastructure

All manifests are managed via Kustomize in `infra/k8s/harness/`.

```bash
# Apply the full Harness overlay (PVCs + Secret template)
kubectl apply -k infra/k8s/harness/

# Verify volumes are bound
kubectl get pvc -n autoswarm
# Expected:
#   autoswarm-skills-pvc       Bound   2Gi  RWX
#   autoswarm-edge-memory-pvc  Bound   5Gi  RWO
```

> [!WARNING]
> Both PVCs default to `storageClassName: standard`. If your cluster uses a different class (e.g., `efs-sc` on EKS, `azurefile` on AKS, `longhorn` on bare-metal), edit `pvc-skills.yaml` before applying.

---

## 2. Mount Volumes in Deployments

Add these blocks to the **Nexus API Deployment** and **Celery worker Deployment**:

```yaml
# spec.template.spec.containers[*].volumeMounts
volumeMounts:
  - name: autoswarm-skills
    mountPath: /var/lib/autoswarm/skills
  - name: autoswarm-edge-memory   # Nexus API only — single writer (RWO)
    mountPath: /var/lib/autoswarm

# spec.template.spec.volumes
volumes:
  - name: autoswarm-skills
    persistentVolumeClaim:
      claimName: autoswarm-skills-pvc
  - name: autoswarm-edge-memory
    persistentVolumeClaim:
      claimName: autoswarm-edge-memory-pvc
```

> [!NOTE]
> Mount `autoswarm-edge-memory-pvc` **only on the Nexus API pod**. SQLite WAL mode is single-writer. Celery workers only need the `autoswarm-skills-pvc` (RWX).

---

## 3. Run Database Migration (Schedules Table)

The Q2 Cron Scheduler feature adds a `schedules` table. Run the Alembic migration before deploying the new image:

```bash
# From inside the nexus-api pod or a migration job:
alembic -c apps/nexus-api/alembic.ini upgrade head

# Or as a K8s Job (recommended):
kubectl run alembic-migrate \
  --image=ghcr.io/madfam-org/nexus-api:latest \
  --restart=Never \
  --env="DATABASE_URL=$DATABASE_URL" \
  -n autoswarm \
  -- alembic upgrade head

# Verify:
kubectl exec -n autoswarm deploy/autoswarm-nexus-api -- \
  python -c "from nexus_api.models import Schedule; print('Schedule table OK')"
```

---

## 4. Populate All Secrets

The `secret-harness.yaml` contains **placeholder** base64 values for all credentials. Replace them before applying.

### Full Secret — Manual (dev/staging only)
```bash
kubectl create secret generic autoswarm-harness-secrets -n autoswarm \
  --from-literal=TELEGRAM_BOT_TOKEN="<token from @BotFather>" \
  --from-literal=TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 32)" \
  --from-literal=DISCORD_WEBHOOK_SECRET="$(openssl rand -hex 32)" \
  --from-literal=SLACK_SIGNING_SECRET="<from Slack App → Basic Information>" \
  --from-literal=TWILIO_AUTH_TOKEN="<from console.twilio.com>" \
  --from-literal=TWILIO_ACCOUNT_SID="<from console.twilio.com>" \
  --from-literal=TAVILY_API_KEY="<from app.tavily.com>" \
  --from-literal=GITHUB_TOKEN="<fine-grained PAT, read:repo scope>" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Production — Sealed Secrets
```bash
kubeseal --fetch-cert --controller-namespace=kube-system > pub-cert.pem

kubectl create secret generic autoswarm-harness-secrets -n autoswarm \
  --from-literal=SLACK_SIGNING_SECRET="..." \
  --from-literal=TWILIO_AUTH_TOKEN="..." \
  ... \
  --dry-run=client -o yaml \
  | kubeseal --cert pub-cert.pem -o yaml \
  > infra/k8s/harness/sealed-secret-harness.yaml

kubectl apply -f infra/k8s/harness/sealed-secret-harness.yaml
```

### ConfigMap — Non-secret values
```bash
kubectl create configmap autoswarm-harness-config -n autoswarm \
  --from-literal=AUTOSWARM_SKILLS_DIR=/var/lib/autoswarm/skills \
  --from-literal=AUTOSWARM_STATE_DB_PATH=/var/lib/autoswarm/autoswarm_state.db \
  --from-literal=GATEWAY_EMAIL_WHITELIST="ops@yourdomain.com,alerts@yourdomain.com" \
  --from-literal=MEMORY_RETENTION_DAYS=30 \
  --from-literal=SKILL_REFINE_INTERVAL_DAYS=7 \
  --dry-run=client -o yaml | kubectl apply -f -
```

Reference both from Deployments:
```yaml
envFrom:
  - secretRef:
      name: autoswarm-harness-secrets
  - configMapRef:
      name: autoswarm-harness-config
```

---

## 5. Configure Celery Beat Schedules

The `refine_skills_task` and `compact_memory_task` Celery tasks must be registered with the Beat scheduler. Add these entries to your Celery Beat configuration (typically in `celery_app.py` or a `beat_schedule` dict):

```python
from celery.schedules import crontab

app.conf.beat_schedule = {
    # Gap 1: Skill Self-Improvement — runs daily at 02:00 UTC
    "refine-skills-daily": {
        "task": "tasks.refine_skills",
        "schedule": crontab(hour=2, minute=0),
    },
    # Gap 2: Memory Compaction — runs weekly on Sunday at 03:00 UTC
    "compact-memory-weekly": {
        "task": "tasks.compact_memory",
        "schedule": crontab(day_of_week=0, hour=3, minute=0),
        "kwargs": {"retention_days": 30},
    },
}
```

Restart the Celery Beat worker to pick up the new schedules:
```bash
kubectl rollout restart deployment/autoswarm-celery-beat -n autoswarm
kubectl rollout status deployment/autoswarm-celery-beat -n autoswarm
```

---

## 6. Register Multi-Channel Gateway Webhooks

### 6a. Telegram
```bash
# 1. Get bot token from @BotFather (already in secret above)

# 2. Register the webhook — replace variables:
TELEGRAM_TOKEN="<your-bot-token>"
WEBHOOK_SECRET="<your-TELEGRAM_WEBHOOK_SECRET>"
API_HOST="https://api.autoswarm.yourdomain.com"

curl -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/setWebhook" \
  -H "Content-Type: application/json" \
  -d "{
    \"url\": \"${API_HOST}/api/v1/gateway/telegram/webhook\",
    \"secret_token\": \"${WEBHOOK_SECRET}\"
  }"

# 3. Verify:
curl "https://api.telegram.org/bot${TELEGRAM_TOKEN}/getWebhookInfo"
```

### 6b. Discord
```bash
APP_ID="<your-Discord-Application-ID>"
BOT_TOKEN="<your-Discord-Bot-Token>"

# Register /initiate_acp slash command globally:
curl -X POST "https://discord.com/api/v10/applications/${APP_ID}/commands" \
  -H "Authorization: Bot ${BOT_TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "initiate_acp",
    "description": "Trigger an Autonomous Cleanroom Protocol run",
    "options": [{"name":"url","description":"Target URL","type":3,"required":true}]
  }'

# In Discord Developer Portal → your app → General Information:
# Set "Interactions Endpoint URL" to:
#   https://api.autoswarm.yourdomain.com/api/v1/gateway/discord/webhook
```

### 6c. Slack
```bash
# 1. Go to https://api.slack.com/apps → Create New App → From Scratch
# 2. Under "OAuth & Permissions" → add Bot Scopes: commands, chat:write
# 3. Under "Slash Commands" → Create New Command:
#      Command:      /initiate_acp
#      Request URL:  https://api.autoswarm.yourdomain.com/api/v1/gateway/slack/webhook
#      Description:  Trigger an ACP run
#      Usage Hint:   <target-url>
# 4. Under "Basic Information" → copy "Signing Secret" → add to SLACK_SIGNING_SECRET secret
# 5. Install to Workspace
```

### 6d. Email — SendGrid Inbound Parse
```bash
# 1. In SendGrid: Settings → Inbound Parse → Add Host & URL
#      Hostname:    mail.autoswarm.yourdomain.com  (or configure MX record)
#      Destination: https://api.autoswarm.yourdomain.com/api/v1/gateway/email/inbound
#      Check "POST the raw, full MIME message"

# 2. Confirm the MX record for your email subdomain points to mx.sendgrid.net
dig MX mail.autoswarm.yourdomain.com

# 3. Whitelist operator addresses in GATEWAY_EMAIL_WHITELIST (ConfigMap above)
```

### 6e. SMS — Twilio
```bash
# 1. Purchase or configure a Twilio number at console.twilio.com
# 2. Under Phone Numbers → Manage → Active Numbers → select your number:
#      A message comes in → Webhook:
#      https://api.autoswarm.yourdomain.com/api/v1/gateway/sms/inbound
#      HTTP POST
# 3. Confirm TWILIO_AUTH_TOKEN and TWILIO_ACCOUNT_SID are in the secret

# Test with Twilio CLI:
twilio api:core:messages:create \
  --from "+15550001234" \
  --to "+15559999999" \
  --body "acp https://example.com"
```

---

## 7. Configure MCP Tool Servers

Ensure the following env vars reach the **Celery worker** container (sourced from the secret and ConfigMap above):

| Variable | Source | Purpose |
|---|---|---|
| `TAVILY_API_KEY` | `autoswarm-harness-secrets` | Tavily web-search MCP server |
| `GITHUB_TOKEN` | `autoswarm-harness-secrets` | GitHub MCP server |
| `AUTOSWARM_SKILLS_DIR` | `autoswarm-harness-config` | Override default skills PVC path |

The `mcp_config.json` in `packages/workflows/` is baked into the container image. No runtime configuration needed beyond the env vars above.

---

## 8. Verify the Full Integration

Run these checks after completing all steps above:

```bash
# 1. Skills volume writable from Celery worker
kubectl exec -n autoswarm deploy/autoswarm-celery -it -- \
  ls -la /var/lib/autoswarm/skills

# 2. Schedules table exists
kubectl exec -n autoswarm deploy/autoswarm-nexus-api -it -- \
  python -c "from nexus_api.models import Schedule; print('OK')"

# 3. Trigger an ACP run → confirm a skill file appears within 60s
curl -X POST https://api.autoswarm.yourdomain.com/api/v1/acp/initiate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "description": "ops smoke test"}'

# 4. FTS5 edge memory is recording
kubectl exec -n autoswarm deploy/autoswarm-nexus-api -it -- python -c "
from nexus_api.memory_store.db import memory_store
hits = memory_store.fts_search('smoke test')
print(f'FTS hits: {len(hits)}')
"

# 5. SkillRefiner beat task fire manually
kubectl exec -n autoswarm deploy/autoswarm-celery -it -- \
  celery -A nexus_api.celery_app call tasks.refine_skills

# 6. MemoryCompactor fire manually
kubectl exec -n autoswarm deploy/autoswarm-celery -it -- \
  celery -A nexus_api.celery_app call tasks.compact_memory --kwargs '{"retention_days": 30}'

# 7. Create a schedule via API
curl -X POST https://api.autoswarm.yourdomain.com/api/v1/schedules \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"cron_expr": "0 9 * * 1", "action": "skill_refine", "description": "Weekly skill tune-up"}'

# 8. Slack smoke test (requires installed bot)
#    Send /initiate_acp https://example.com in any channel with the bot — expect ✅ ephemeral reply

# 9. SMS smoke test (requires Twilio number)
#    Text "acp https://example.com" to your Twilio number — expect 200 from webhook
```

---

## 9. Complete Environment Variable Reference

All variables are declared in `apps/nexus-api/nexus_api/config.py`.

| Variable | Default | Secret? | Required in Prod? | Description |
|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `""` | ✅ | If using Telegram | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | `""` | ✅ | If using Telegram | HMAC token set on `setWebhook` |
| `DISCORD_WEBHOOK_SECRET` | `""` | ✅ | If using Discord | HMAC secret for payload validation |
| `SLACK_SIGNING_SECRET` | `""` | ✅ | If using Slack | From Slack App → Basic Information |
| `GATEWAY_EMAIL_WHITELIST` | `""` | ConfigMap | If using Email | Comma-separated authorised sender addresses |
| `TWILIO_AUTH_TOKEN` | `""` | ✅ | If using SMS | From console.twilio.com |
| `TWILIO_ACCOUNT_SID` | `""` | ✅ | If using SMS | From console.twilio.com |
| `TAVILY_API_KEY` | `""` | ✅ | For MCP web search | From app.tavily.com |
| `GITHUB_TOKEN` | `""` | ✅ | For MCP GitHub access | Fine-grained PAT, read:repo scope |
| `AUTOSWARM_SKILLS_DIR` | `/var/lib/autoswarm/skills` | ConfigMap | ✅ | PVC mount path for skill scripts |
| `AUTOSWARM_STATE_DB_PATH` | `/var/lib/autoswarm/autoswarm_state.db` | ConfigMap | ✅ | SQLite FTS5 edge memory location |
| `SKILL_REFINE_INTERVAL_DAYS` | `7` | ConfigMap | Optional | Days before a skill is considered stale |
| `MEMORY_RETENTION_DAYS` | `30` | ConfigMap | Optional | Transcripts older than N days are compacted |


---

## 1. Apply Kubernetes Infrastructure

All manifests live in `infra/k8s/harness/`.

```bash
# Apply the full Harness overlay (PVCs + Secret template)
kubectl apply -k infra/k8s/harness/

# Verify volumes are bound
kubectl get pvc -n autoswarm
# Expected:
#   autoswarm-skills-pvc       Bound   ...
#   autoswarm-edge-memory-pvc  Bound   ...
```

> [!WARNING]
> Both PVCs use `storageClassName: standard`. If your cluster uses a different RWX-capable StorageClass (e.g., `efs-sc` on EKS, `azurefile` on AKS), edit `pvc-skills.yaml` before applying.

---

## 2. Mount Volumes in Deployments

Add the following `volumeMounts` and `volumes` blocks to the **Nexus API** and **Celery worker** Deployments:

```yaml
# In spec.template.spec.containers[*]:
volumeMounts:
  - name: autoswarm-skills
    mountPath: /var/lib/autoswarm/skills
  - name: autoswarm-edge-memory
    mountPath: /var/lib/autoswarm         # SQLite db lives here

# In spec.template.spec:
volumes:
  - name: autoswarm-skills
    persistentVolumeClaim:
      claimName: autoswarm-skills-pvc
  - name: autoswarm-edge-memory
    persistentVolumeClaim:
      claimName: autoswarm-edge-memory-pvc
```

> [!NOTE]
> `autoswarm-edge-memory-pvc` is `ReadWriteOnce` — mount it **only on the Nexus API pod** (single writer). Celery workers only need `autoswarm-skills-pvc` (`ReadWriteMany`).

---

## 3. Populate Secrets

The `secret-harness.yaml` file contains **placeholder** base64 values. Replace them before applying, or better yet, use Sealed Secrets / External Secrets Operator.

### Option A — Manual (dev/staging only)
```bash
kubectl create secret generic autoswarm-harness-secrets -n autoswarm \
  --from-literal=TELEGRAM_BOT_TOKEN="<token from @BotFather>" \
  --from-literal=TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 32)" \
  --from-literal=DISCORD_WEBHOOK_SECRET="$(openssl rand -hex 32)" \
  --from-literal=TAVILY_API_KEY="<from app.tavily.com>" \
  --from-literal=GITHUB_TOKEN="<fine-grained PAT, read:repo scope>" \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Option B — Sealed Secrets (recommended for production)
```bash
# Encrypt each literal into a SealedSecret
kubeseal --fetch-cert --controller-namespace=kube-system > pub-cert.pem

kubectl create secret generic autoswarm-harness-secrets -n autoswarm \
  --from-literal=TELEGRAM_BOT_TOKEN="..." \
  --dry-run=client -o yaml \
  | kubeseal --cert pub-cert.pem -o yaml > infra/k8s/harness/sealed-secret-harness.yaml

kubectl apply -f infra/k8s/harness/sealed-secret-harness.yaml
```

---

## 4. Register Gateway Webhooks

### Telegram
1. Open a chat with [@BotFather](https://t.me/botfather) and create a bot → copy the token.
2. Set the webhook URL pointing to your production Nexus API:
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://api.autoswarm.yourdomain.com/api/v1/gateway/telegram/webhook"}'
```
3. Optionally set a `secret_token` for payload verification:
```bash
curl -X POST "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d '{"url": "...", "secret_token": "<TELEGRAM_WEBHOOK_SECRET>"}'
```

### Discord
1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → your app → Interactions Endpoint URL.
2. Set it to: `https://api.autoswarm.yourdomain.com/api/v1/gateway/discord/webhook`
3. For slash command triggering (`/initiate_acp`), register the command:
```bash
curl -X POST "https://discord.com/api/v10/applications/<APP_ID>/commands" \
  -H "Authorization: Bot <BOT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"name":"initiate_acp","description":"Trigger an ACP run","options":[{"name":"url","description":"Target URL","type":3,"required":true}]}'
```

---

## 5. Configure MCP Tool Servers

The Phase I Analyst bootstraps MCP servers using `packages/workflows/mcp_config.json`. Ensure the following environment variables are available inside the Celery worker container:

| Variable | Source | Purpose |
|---|---|---|
| `TAVILY_API_KEY` | `autoswarm-harness-secrets` | Tavily web-search MCP server |
| `GITHUB_TOKEN` | `autoswarm-harness-secrets` | GitHub MCP server |
| `AUTOSWARM_SKILLS_DIR` | ConfigMap or env | Override default skills PVC path |

Reference these from the Deployment `envFrom`:
```yaml
envFrom:
  - secretRef:
      name: autoswarm-harness-secrets
```

---

## 6. Verify the Integration

```bash
# 1. Check the skills volume is writable from the Celery worker
kubectl exec -n autoswarm deploy/autoswarm-celery -it -- \
  ls /var/lib/autoswarm/skills

# 2. Trigger a test ACP run and confirm a skill file appears
curl -X POST https://api.autoswarm.yourdomain.com/api/v1/acp/initiate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"target_url": "https://example.com", "description": "parity smoke test"}'

# 3. Validate FTS5 edge memory is recording transcripts
kubectl exec -n autoswarm deploy/autoswarm-nexus-api -it -- \
  python -c "
from nexus_api.memory_store.db import memory_store
results = memory_store.fts_search('smoke test')
print(f'FTS hits: {len(results)}')
"

# 4. Confirm gateway is reachable
curl -X POST https://api.autoswarm.yourdomain.com/api/v1/gateway/telegram/webhook \
  -H "Content-Type: application/json" \
  -d '{"message":{"text":"/initiate_acp https://example.com"}}'
```

---

## 7. Environment Variable Reference

All new variables are declared in `apps/nexus-api/nexus_api/config.py` and read from the environment or `.env` file at startup.

| Variable | Default | Required in Prod? | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | `""` | ✅ if using Telegram | Bot token from @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | `""` | ✅ | HMAC secret for Telegram payload validation |
| `DISCORD_WEBHOOK_SECRET` | `""` | ✅ if using Discord | HMAC secret for Discord payload validation |
| `TAVILY_API_KEY` | `""` | ✅ for MCP web search | From app.tavily.com |
| `GITHUB_TOKEN` | `""` | ✅ for MCP GitHub access | Fine-grained PAT |
| `AUTOSWARM_SKILLS_DIR` | `/var/lib/autoswarm/skills` | ✅ | PVC mount path for skill scripts |
| `AUTOSWARM_STATE_DB_PATH` | `/var/lib/autoswarm/autoswarm_state.db` | ✅ | SQLite edge memory location |

## Harness gateway coverage addendum

Canonical Nexus API route prefix: `/api/v1/gateway/<channel>/...`.
Legacy compatibility route prefix: `/api/v1/gateway/gateway/<channel>/...` remains mounted for already-registered webhooks and should be phased out during the next provider registration pass.

### Shared Harness commands

The common command surface is available to native handlers where wired and to signed relay handlers:

- `acp <url>` or `/initiate_acp <url>` dispatches an ACP task after SSRF-oriented URL validation.
- `status [query]` and `recall <query>` return recent transcript hits from EdgeMemoryDB.
- `remember <note>` stores an operator note in the transcript memory store.
- `pending` intentionally returns `needs_authenticated_bridge` until channel identities are bound to Janua/Selva tenant users.

### Signed relay contract

Use the signed relay adapters for platforms where the native provider contract is unavailable, unstable, or requires a local bridge process:

- Microsoft Teams: `POST /api/v1/gateway/teams/webhook`, secret `TEAMS_WEBHOOK_SECRET`.
- IRC bridge: `POST /api/v1/gateway/irc/webhook`, secret `IRC_WEBHOOK_SECRET`.
- QQ Bot bridge: `POST /api/v1/gateway/qq/webhook`, secret `QQ_WEBHOOK_SECRET`.
- Yuanbao bridge: `POST /api/v1/gateway/yuanbao/webhook`, secret `YUANBAO_WEBHOOK_SECRET`.

Accepted authentication forms:

- `Authorization: Bearer <secret>`
- `Authorization: HMAC <base64(hmac_sha256(body, secret))>`
- `X-Webhook-Signature: sha256=<hex_hmac_sha256(body, secret)>`

Relay payload text is read from `text`, `message`, `content`, or `body`. Actor labels are read from `actor`, `user`, `username`, `sender`, or `from`.

### HITL bridge requirement

Approval actions must not be accepted from chat channels until a channel identity maps to a Janua-authenticated Selva user and tenant. The current safe behavior for `pending` is explicit refusal with `needs_authenticated_bridge`. The next implementation step is a tenant-bound operator identity table plus command handlers for `pending`, `approve <id>`, and `deny <id> <reason>` that call the existing `/api/v1/approvals` APIs with idempotency keys.
