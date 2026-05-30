"""Tulana SKU campaign planning and draft graph (Phase 2.2–2.3)."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from ..event_emitter import instrumented_node
from .base import BaseGraphState
from .base import run_async as _run_async

logger = logging.getLogger(__name__)


class CampaignState(BaseGraphState, TypedDict, total=False):
    """State for Tulana-backed campaign planning + draft generation."""

    tulana_pack: dict[str, Any]
    campaign_lane: str
    draft_variants: list[str]
    guardrail_violations: list[str]
    campaign_category: str


def guard_campaign_draft(draft: str, do_not_claim: list[str]) -> tuple[str, list[str]]:
    """Return scrubbed draft and any phrases from do_not_claim still present."""
    violations: list[str] = []
    scrubbed = draft
    for phrase in do_not_claim:
        cleaned = phrase.strip()
        if not cleaned:
            continue
        pattern = re.compile(re.escape(cleaned), re.IGNORECASE)
        if pattern.search(scrubbed):
            violations.append(cleaned)
            scrubbed = pattern.sub("", scrubbed)
    scrubbed = re.sub(r"\s{2,}", " ", scrubbed).strip()
    return scrubbed, violations


def _extract_tulana_pack(payload: dict[str, Any]) -> dict[str, Any] | None:
    pack = payload.get("tulana_pack")
    if isinstance(pack, dict):
        return pack
    return None


def _proof_points_context(pack: dict[str, Any]) -> str:
    lines: list[str] = []
    for point in pack.get("proof_points") or []:
        if not isinstance(point, dict):
            continue
        label = point.get("label", "")
        source = point.get("source", "")
        url = point.get("url", "")
        line = f"- {label} (source: {source}"
        if url:
            line += f", {url}"
        line += ")"
        lines.append(line)
    return "\n".join(lines) if lines else "- (waived — no proof points in export)"


@instrumented_node
def load_tulana_pack(state: CampaignState) -> CampaignState:
    """Load and validate Tulana pack from task state."""
    messages = state.get("messages", [])
    pack = state.get("tulana_pack")
    if not isinstance(pack, dict):
        payload = state.get("payload", {}) or {}
        pack = _extract_tulana_pack(payload)
    if pack is None:
        return {
            **state,
            "messages": messages,
            "status": "error",
            "error_message": "missing tulana_pack in task payload",
        }

    required = ("sku_key", "audience", "ga_readiness", "do_not_claim", "last_verified_at")
    missing = [field for field in required if not pack.get(field)]
    if missing:
        return {
            **state,
            "messages": messages,
            "status": "error",
            "error_message": f"tulana_pack missing fields: {', '.join(missing)}",
        }

    category = str(
        state.get("campaign_category")
        or (state.get("payload", {}) or {}).get("campaign_category")
        or "sku_campaign_planning"
    )
    msg = AIMessage(
        content=f"Loaded Tulana pack for SKU {pack.get('sku_key')}.",
        additional_kwargs={"action_category": "api_call"},
    )
    return {
        **state,
        "messages": [*messages, msg],
        "tulana_pack": pack,
        "campaign_category": category,
        "status": "loaded",
    }


@instrumented_node
def plan_lane(state: CampaignState) -> CampaignState:
    """Derive campaign lane identifier from SKU + audience."""
    messages = state.get("messages", [])
    pack = state.get("tulana_pack") or {}
    sku_key = str(pack.get("sku_key", "unknown"))
    audience = str(pack.get("audience", "general"))
    readiness = str(pack.get("ga_readiness", "unknown"))
    lane = f"{sku_key}::{audience}::{readiness}"

    msg = AIMessage(
        content=f"Planned campaign lane: {lane}",
        additional_kwargs={"action_category": "planning"},
    )
    return {
        **state,
        "messages": [*messages, msg],
        "campaign_lane": lane,
        "status": "planned",
    }


@instrumented_node
def draft_copy(state: CampaignState) -> CampaignState:
    """Generate draft copy using Tulana proof points only; scrub do_not_claim phrases."""
    messages = state.get("messages", [])
    pack = state.get("tulana_pack") or {}
    do_not_claim = [str(x) for x in (pack.get("do_not_claim") or []) if str(x).strip()]
    proof_context = _proof_points_context(pack)
    value_prop = str(pack.get("value_prop") or "").strip()
    audience = str(pack.get("audience") or "")
    sku_key = str(pack.get("sku_key") or "")

    prompt = (
        f"SKU: {sku_key}\n"
        f"Audience: {audience}\n"
        f"Value proposition (from Tulana): {value_prop or '(none)'}\n\n"
        f"Approved proof points ONLY:\n{proof_context}\n\n"
        "Write two short campaign copy variants (email subject + 2-sentence body each). "
        "Use ONLY the proof points above. Do not invent certifications, pricing, or legal claims."
    )

    raw_draft: str
    try:
        from ..inference import call_llm, get_model_router

        router = get_model_router()
        skill_ctx = state.get("agent_system_prompt", "")
        system_prompt = (f"{skill_ctx}\n\n" if skill_ctx else "") + (
            "You are a campaign copywriter for Selva. "
            "Output JSON: {\"variants\": [\"variant1\", \"variant2\"]}. "
            "Never include content from a do-not-claim list."
        )
        llm_out = _run_async(
            call_llm(
                router,
                messages=[{"role": "user", "content": prompt}],
                system_prompt=system_prompt,
                task_type="research",
            )
        )
        parsed = json.loads(llm_out)
        variants = parsed.get("variants") if isinstance(parsed, dict) else None
        if isinstance(variants, list) and variants:
            raw_draft = "\n\n---\n\n".join(str(v) for v in variants[:3])
        else:
            raw_draft = str(llm_out)
    except Exception:
        logger.debug("LLM unavailable; using template draft", exc_info=True)
        raw_draft = (
            f"Variant A — Subject: {sku_key} for {audience}\n"
            f"Body: {value_prop or 'Evidence-backed positioning from Tulana export.'}\n\n"
            f"Variant B — Subject: Learn about {sku_key}\n"
            f"Body: Based on verified proof points:\n{proof_context}"
        )

    scrubbed, violations = guard_campaign_draft(raw_draft, do_not_claim)
    variants_out = [v.strip() for v in scrubbed.split("\n\n---\n\n") if v.strip()]
    if not variants_out:
        variants_out = [scrubbed] if scrubbed else []

    msg = AIMessage(
        content=(
            f"Generated {len(variants_out)} draft variant(s); "
            f"violations scrubbed: {len(violations)}"
        ),
        additional_kwargs={"action_category": "content_generation"},
    )
    status = "draft_ready" if not violations else "draft_ready_with_scrub"
    return {
        **state,
        "messages": [*messages, msg],
        "draft_variants": variants_out,
        "guardrail_violations": violations,
        "status": status,
    }


def _build_social_schedule_body(
    *,
    pack: dict[str, Any],
    variants: list[str],
    payload_root: dict[str, Any],
) -> dict[str, Any]:
    """Build ``CampaignSocialScheduleRequest``-shaped body for nexus-api."""
    sku_key = str(pack.get("sku_key") or "campaign")
    audience = str(pack.get("audience") or "general")
    platform = str(payload_root.get("auto_schedule_platform") or "reddit").strip().lower()
    if platform not in {"reddit", "bluesky", "mastodon", "email"}:
        platform = "reddit"

    primary_copy = variants[0] if variants else str(pack.get("value_prop") or sku_key)
    title = f"{sku_key} for {audience}"[:300]
    subreddit = str(payload_root.get("reddit_subreddit") or "selva")

    posts: list[dict[str, Any]] = []
    base = datetime.now(UTC).replace(second=0, microsecond=0) + timedelta(hours=1)
    offsets_days = payload_root.get("auto_schedule_offsets_days") or [1, 2, 3]
    if not isinstance(offsets_days, list):
        offsets_days = [1, 2, 3]

    for idx, day_offset in enumerate(offsets_days[:3]):
        try:
            day_n = int(day_offset)
        except (TypeError, ValueError):
            day_n = idx + 1
        when = base + timedelta(days=day_n)
        variant = variants[idx % len(variants)] if variants else primary_copy
        if platform == "reddit":
            post_payload = {
                "subreddit": subreddit,
                "title": title,
                "body": variant[:4000],
            }
        elif platform == "bluesky":
            post_payload = {"text": variant[:300]}
        elif platform == "mastodon":
            post_payload = {
                "instance": str(payload_root.get("mastodon_instance") or "mastodon.social"),
                "status": variant[:500],
            }
        else:
            recipient = str(payload_root.get("email_recipient") or "campaign@example.com")
            post_payload = {
                "recipient": recipient,
                "subject": title,
                "body": variant[:4000],
            }
        posts.append({"scheduled_for": when.isoformat(), "payload": post_payload})

    return {
        "sku_key": sku_key,
        "platform": platform,
        "require_hitl": payload_root.get("auto_schedule_require_hitl", True),
        "campaign_id": payload_root.get("campaign_id"),
        "persona_id": payload_root.get("persona_id"),
        "posts": posts,
    }


@instrumented_node
def schedule_social(state: CampaignState) -> CampaignState:
    """Enqueue HITL-gated social cadence via nexus-api after drafts are ready."""
    messages = state.get("messages", [])
    status = state.get("status") or ""
    if status not in {"draft_ready", "draft_ready_with_scrub"}:
        return {**state, "messages": messages}

    payload_root = state.get("payload", {}) or {}
    if payload_root.get("auto_schedule_social") is False:
        msg = AIMessage(content="Social auto-schedule skipped (disabled in payload).")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "draft_ready",
        }

    pack = state.get("tulana_pack") or {}
    variants = state.get("draft_variants") or []
    org_id = state.get("org_id") or payload_root.get("org_id") or ""
    if not org_id:
        return {
            **state,
            "messages": messages,
            "status": "schedule_skipped_no_org",
        }

    body = _build_social_schedule_body(pack=pack, variants=variants, payload_root=payload_root)

    scheduled_count = 0
    error_detail: str | None = None
    try:
        import httpx

        from ..auth import get_worker_auth_headers
        from ..config import get_settings

        settings = get_settings()
        url = f"{settings.nexus_api_url.rstrip('/')}/api/v1/campaigns/schedule-social"
        headers = {
            **get_worker_auth_headers(org_id=org_id),
            "Content-Type": "application/json",
            "Idempotency-Key": f"campaign-graph:{state.get('task_id', 'unknown')}:{pack.get('sku_key')}",
        }

        async def _post() -> httpx.Response:
            async with httpx.AsyncClient(timeout=15.0) as client:
                return await client.post(url, headers=headers, json=body)

        response = _run_async(_post())
        if response.status_code in {200, 201}:
            data = response.json()
            scheduled_count = int(data.get("count") or 0)
        else:
            error_detail = f"HTTP {response.status_code}: {response.text[:200]}"
    except Exception as exc:
        logger.warning("Campaign schedule-social failed", exc_info=True)
        error_detail = str(exc)

    if error_detail:
        msg = AIMessage(content=f"Social schedule failed: {error_detail[:500]}")
        return {
            **state,
            "messages": [*messages, msg],
            "status": "schedule_failed",
        }

    msg = AIMessage(
        content=f"Scheduled {scheduled_count} social post(s) with HITL gate.",
        additional_kwargs={"action_category": "api_call"},
    )
    return {
        **state,
        "messages": [*messages, msg],
        "status": "scheduled",
    }


def build_campaign_graph() -> StateGraph:
    """Construct Tulana campaign planning + draft graph."""
    graph = StateGraph(CampaignState)
    graph.add_node("load_tulana_pack", load_tulana_pack)
    graph.add_node("plan_lane", plan_lane)
    graph.add_node("draft_copy", draft_copy)
    graph.add_node("schedule_social", schedule_social)
    graph.add_edge(START, "load_tulana_pack")
    graph.add_edge("load_tulana_pack", "plan_lane")
    graph.add_edge("plan_lane", "draft_copy")
    graph.add_edge("draft_copy", "schedule_social")
    graph.add_edge("schedule_social", END)
    return graph
