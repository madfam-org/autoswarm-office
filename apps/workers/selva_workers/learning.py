"""Post-task learning: experience recording, reflexion, bandit rewards, stats."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def record_experience(
    agent_id: str,
    agent_role: str,
    task_description: str,
    graph_type: str,
    result: Any | None,
    status: str,
    duration_seconds: float | None = None,
    feedback: str | None = None,
    error_message: str | None = None,
) -> None:
    """Record task outcome in ExperienceStore (per-role) and MemoryStore (per-agent).

    Fire-and-forget — exceptions are logged but never raised.
    """
    try:
        from selva_memory import (
            ExperienceRecord,
            ExperienceStore,
            get_embedding_provider,
            get_memory_manager,
        )

        from .config import get_settings

        settings = get_settings()

        # Determine score: completed=1.0, denied=0.2, failed=0.0
        score_map = {"completed": 1.0, "pushed": 1.0, "denied": 0.2, "blocked": 0.2}
        score = score_map.get(status, 0.0)

        # Build approach string
        result_summary = ""
        if isinstance(result, dict):
            result_summary = str(result)[:300]
        elif isinstance(result, str):
            result_summary = result[:300]
        approach = f"[{graph_type}] {result_summary}" if result_summary else f"[{graph_type}] task"

        # Build outcome string
        parts = [f"status={status}"]
        if duration_seconds is not None:
            parts.append(f"duration={duration_seconds:.1f}s")
        if feedback:
            parts.append(f"feedback={feedback[:200]}")
        if error_message:
            parts.append(f"error={error_message[:200]}")
        outcome = ", ".join(parts)

        # Per-role experience
        embedder = get_embedding_provider()
        experience_store = ExperienceStore(
            role=agent_role,
            embedding_provider=embedder,
            persist_dir=settings.memory_persist_dir,
        )
        record = ExperienceRecord(
            task_pattern=task_description[:500],
            approach=approach,
            outcome=outcome,
            score=score,
            metadata={"graph_type": graph_type, "agent_id": agent_id},
        )
        await experience_store.record(record)
        logger.debug(
            "Recorded experience for role=%s agent=%s score=%.1f",
            agent_role,
            agent_id,
            score,
        )

        # Per-agent memory
        memory_manager = get_memory_manager(persist_dir=settings.memory_persist_dir)
        memory_text = f"Task: {task_description[:300]} | Outcome: {outcome}"
        await memory_manager.store_memory(
            agent_id=agent_id,
            text=memory_text,
            metadata={"graph_type": graph_type, "score": score},
        )

    except Exception:
        logger.warning("Failed to record experience for agent %s", agent_id, exc_info=True)


async def generate_reflexion(
    agent_id: str,
    agent_role: str,
    task_description: str,
    graph_type: str,
    error_message: str | None = None,
    feedback: str | None = None,
) -> None:
    """Generate a self-critique reflection on failure (Reflexion pattern).

    Calls LLM for structured analysis; falls back to basic text if unavailable.
    Stores the reflection in ExperienceStore with score=0.3.

    Fire-and-forget — exceptions are logged but never raised.
    """
    try:
        from selva_memory import ExperienceRecord, ExperienceStore, get_embedding_provider

        from .config import get_settings

        settings = get_settings()

        # Try LLM-based reflection
        reflection_text: str | None = None
        try:
            from .inference import call_llm, get_model_router

            router = get_model_router()
            prompt = (
                f"Task: {task_description[:300]}\n"
                f"Graph type: {graph_type}\n"
                f"Error: {error_message or 'unknown'}\n"
                f"Feedback: {feedback or 'none'}\n\n"
                "Analyze what went wrong. Provide 2-3 actionable lessons learned "
                "that would help succeed on a similar task next time. Be concise."
            )
            reflection_text = await call_llm(
                router,
                messages=[{"role": "user", "content": prompt}],
                system_prompt="You are an AI agent performing self-critique after a failed task.",
                task_type="review",
            )
        except Exception:
            logger.debug("LLM unavailable for reflexion, using fallback")

        # Fallback reflection
        if not reflection_text or reflection_text.startswith("[LLM unavailable"):
            parts = [f"Failed task: {task_description[:200]}"]
            if error_message:
                parts.append(f"Error encountered: {error_message[:200]}")
            if feedback:
                parts.append(f"Human feedback: {feedback[:200]}")
            parts.append("Lesson: Review approach and handle edge cases before execution.")
            reflection_text = " | ".join(parts)

        # Store reflection in experience store
        embedder = get_embedding_provider()
        experience_store = ExperienceStore(
            role=agent_role,
            embedding_provider=embedder,
            persist_dir=settings.memory_persist_dir,
        )
        record = ExperienceRecord(
            task_pattern=task_description[:500],
            approach=f"[reflexion] {reflection_text[:500]}",
            outcome=f"reflection on failure: {error_message or 'unknown'}",
            score=0.3,
            metadata={"type": "reflection", "graph_type": graph_type, "agent_id": agent_id},
        )
        await experience_store.record(record)
        logger.debug("Stored reflexion for agent %s role=%s", agent_id, agent_role)

    except Exception:
        logger.warning("Failed to generate reflexion for agent %s", agent_id, exc_info=True)


async def update_agent_performance(
    nexus_url: str,
    agent_id: str,
    status: str,
    duration_seconds: float | None = None,
    was_approval_denied: bool = False,
    org_id: str | None = None,
) -> None:
    """Fire-and-forget PATCH to /api/v1/agents/{agent_id}/stats.

    Follows the same pattern as task_status.py.

    Args:
        org_id: Target tenant org_id for the X-Selva-Tenant-Org header
            so nexus-api routes the worker token to the correct tenant
            scope. Agent rows are tenant-scoped — callers SHOULD pass it.
    """
    if agent_id == "unknown":
        return

    try:
        from .auth import get_worker_auth_headers
        from .http_retry import fire_and_forget_request

        body: dict[str, Any] = {}
        if status in ("completed", "pushed"):
            body["tasks_completed_delta"] = 1
        elif status in ("failed", "error", "timeout"):
            body["tasks_failed_delta"] = 1

        if was_approval_denied:
            body["approval_denial_delta"] = 1
        elif status in ("completed", "pushed"):
            body["approval_success_delta"] = 1

        if duration_seconds is not None:
            body["task_duration_seconds"] = duration_seconds

        if not body:
            return

        url = f"{nexus_url}/api/v1/agents/{agent_id}/stats"
        success = await fire_and_forget_request(
            "PATCH",
            url,
            json=body,
            headers=get_worker_auth_headers(org_id=org_id),
            timeout=5.0,
        )
        if not success:
            logger.warning("Failed to update stats for agent %s", agent_id)

    except Exception:
        logger.warning("Failed to update agent performance for %s", agent_id, exc_info=True)


async def update_bandit_reward(agent_id: str, reward: float) -> None:
    """Update the Thompson Sampling bandit with a task outcome reward.

    Fire-and-forget — exceptions are logged but never raised.
    """
    if agent_id == "unknown":
        return

    try:
        from selva_orchestrator.bandit import ThompsonBandit

        from .config import get_settings

        settings = get_settings()
        bandit = ThompsonBandit(persist_path=settings.bandit_persist_path)
        bandit.update(agent_id, reward)
        logger.debug("Updated bandit reward for agent %s: %.2f", agent_id, reward)

    except Exception:
        logger.warning("Failed to update bandit reward for agent %s", agent_id, exc_info=True)
