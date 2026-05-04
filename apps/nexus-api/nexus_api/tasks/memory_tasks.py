"""
Memory Compactor Celery task — Gap 2: Memory LLM Summarization.

Periodically reads old FTS5 transcript rows, invokes madfam_inference to
produce a compressed structured summary, and replaces the verbose rows with
the distilled version — mirroring Hermes Agent's memory compression loop.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

SUMMARIZE_PROMPT = """\
You are a technical summarizer for an AI orchestration platform. The following is a \
raw conversation transcript from one ACP pipeline run. Produce a concise, structured \
summary in 3-5 bullet points capturing: what was attempted, key findings, outcome, \
and any errors. Use plain text — no markdown headers.

## Transcript
{transcript}
"""


def _get_old_run_ids(memory_store, before_days: int) -> list[str]:
    """Return run_ids whose episodes started more than before_days ago."""
    cutoff = time.time() - (before_days * 86400)
    cursor = memory_store._conn.execute(
        "SELECT DISTINCT run_id FROM conversation_episodes WHERE started_at < ?",
        (cutoff,),
    )
    return [row["run_id"] for row in cursor.fetchall()]


def _fetch_raw_transcript(memory_store, run_id: str) -> str:
    """Concatenate all raw transcript content for a run into a single string."""
    cursor = memory_store._conn.execute(
        """
        SELECT t.role, t.content FROM transcripts t
        JOIN conversation_episodes e ON t.episode_id = e.id
        WHERE e.run_id = ? AND t.role != 'summary'
        ORDER BY t.timestamp ASC
        """,
        (run_id,),
    )
    rows = cursor.fetchall()
    return "\n".join(f"[{r['role']}] {r['content']}" for r in rows)


def _replace_with_summary(memory_store, run_id: str, summary: str) -> None:
    """Delete old raw rows and insert a single compressed summary row."""
    # Get episode id
    cursor = memory_store._conn.execute(
        "SELECT id FROM conversation_episodes WHERE run_id = ?", (run_id,)
    )
    row = cursor.fetchone()
    if not row:
        return
    episode_id = row["id"]

    # Delete raw rows (triggers will clean up FTS index)
    memory_store._conn.execute(
        "DELETE FROM transcripts WHERE episode_id = ? AND role != 'summary'",
        (episode_id,),
    )
    # Insert summary
    memory_store._conn.execute(
        "INSERT INTO transcripts (episode_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
        (episode_id, "summary", summary, time.time()),
    )
    logger.info("Compacted memory for run_id=%s", run_id)


async def compact_memory(retention_days: int = 30) -> dict:
    """
    Core async compaction logic — importable for testing without Celery.
    Returns a summary of runs compacted.
    """
    from nexus_api.memory_store.db import memory_store

    old_runs = _get_old_run_ids(memory_store, before_days=retention_days)
    if not old_runs:
        logger.info("MemoryCompactor: no stale runs found.")
        return {"compacted": 0, "run_ids": []}

    try:
        # `get_default_router` is exported lazily by `madfam_inference`'s
        # __init__ via a runtime alias that mypy can't resolve from the
        # public package surface.  The fallback `except` block below
        # handles ImportError/AttributeError so this is safe at runtime.
        from madfam_inference import get_default_router  # type: ignore[attr-defined]
        from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity

        router = get_default_router()
        llm_available = True
    except Exception:
        llm_available = False
        logger.warning("MemoryCompactor: madfam_inference unavailable — using extractive summary.")

    compacted = []
    for run_id in old_runs:
        raw = _fetch_raw_transcript(memory_store, run_id)
        if not raw.strip():
            continue

        if llm_available:
            try:
                request = InferenceRequest(
                    messages=[
                        {
                            "role": "user",
                            "content": SUMMARIZE_PROMPT.format(transcript=raw[:4000]),
                        }
                    ],
                    system_prompt="You are a concise technical summarizer. Output plain text only.",
                    policy=RoutingPolicy(
                        sensitivity=Sensitivity.CONFIDENTIAL,
                        task_type="summarization",
                        temperature=0.3,
                        max_tokens=512,
                    ),
                )
                response = await router.complete(request)
                summary = response.content
            except Exception as exc:
                logger.error("LLM summarization failed for run %s: %s", run_id, exc)
                summary = f"[Auto-summary unavailable] Raw transcript length: {len(raw)} chars."
        else:
            # Extractive fallback: first 3 lines
            lines = [ln for ln in raw.split("\n") if ln.strip()]
            summary = " | ".join(lines[:3]) + f" ... [{len(lines)} total entries]"

        _replace_with_summary(memory_store, run_id, summary)
        compacted.append(run_id)

    return {"compacted": len(compacted), "run_ids": compacted}
