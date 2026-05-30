"""Tulana SKU campaign planning and draft graph (Phase 2.2–2.3)."""

from __future__ import annotations

import json
import logging
import re
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


def build_campaign_graph() -> StateGraph:
    """Construct Tulana campaign planning + draft graph."""
    graph = StateGraph(CampaignState)
    graph.add_node("load_tulana_pack", load_tulana_pack)
    graph.add_node("plan_lane", plan_lane)
    graph.add_node("draft_copy", draft_copy)
    graph.add_edge(START, "load_tulana_pack")
    graph.add_edge("load_tulana_pack", "plan_lane")
    graph.add_edge("plan_lane", "draft_copy")
    graph.add_edge("draft_copy", END)
    return graph
