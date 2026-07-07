# Selva Inference Gateway

The OpenAI-compatible `/v1` inference proxy, extracted from nexus-api
(RFC 0034 P2) so the LLM chokepoint every ecosystem service routes through has
its own deployable and uptime.

- **Public endpoint:** `https://inference.selva.town` (`/v1/chat/completions`,
  `/v1/embeddings`, `/health`)
- **Port:** 4306 · **Image:** `ghcr.io/madfam-org/selva-inference-gateway`
- **Same code, own process:** mounts nexus-api's `inference_proxy` router and
  imports the decoupled `nexus_api` slice (auth, database, models, the USD
  usage ledger) plus `packages/inference`. No re-implementation.
- **No Redis dependency** — a Redis outage must never take inference down.

Run locally:

```bash
uv run --project apps/inference-gateway uvicorn inference_gateway.main:app --port 4306
```

Deploy: built by `.github/workflows/deploy.yml` (cosign-signed, digest-pinned
into `infra/k8s/production/kustomization.yaml`), synced by ArgoCD into the
`selva` namespace. Cutover procedure: `internal-devops`
`runbooks/2026-07-07-selva-inference-gateway-cutover.md`.
