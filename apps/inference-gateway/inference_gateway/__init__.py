"""Selva inference gateway — the OpenAI-compatible /v1 proxy as its own service.

RFC 0034 P2: extracted from nexus-api so that the LLM chokepoint every
ecosystem service routes through has its own deployable, process, and uptime —
decoupled from campaign/agent/audit deploys of the monolith. It reuses the
SAME inference core (packages/inference) and the SAME auth + USD usage ledger
(the decoupled nexus_api slice), so there is one source of truth for routing,
pricing, and identity across both deployables.
"""
