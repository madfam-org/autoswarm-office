"""Stage 2 — exercise the drafter (LLM first-touch email generator)."""

from __future__ import annotations

import contextlib
import time

from ..probe import ProbeContext, ProbeStep, StageResult, StageStatus


class DraftStep(ProbeStep):
    """Hit the draft endpoint and confirm we got a non-placeholder body.

    Selva CRM graph refuses to send when the LLM returns the literal
    ``[LLM unavailable`` sentinel (see CLAUDE.md v2.1.1). We check for that
    explicitly so the probe can distinguish "LLM is down" from "everything
    else is broken".
    """

    name = "drafter.first_touch"

    async def run(self, ctx: ProbeContext) -> StageResult:
        t0 = time.perf_counter()

        base_url = ctx.env.get("NEXUS_API_URL")
        api_token = ctx.env.get("NEXUS_PROBE_TOKEN")
        if not base_url or not api_token:
            return StageResult(
                name=self.name,
                status=StageStatus.SKIPPED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail="NEXUS_API_URL or NEXUS_PROBE_TOKEN not set",
            )

        lead_id = ctx.state.get("lead_id")
        if not lead_id:
            return StageResult(
                name=self.name,
                status=StageStatus.SKIPPED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail="no lead_id in ctx.state (prior stage skipped/failed)",
            )

        assert ctx.http is not None
        url = f"{base_url.rstrip('/')}/api/v1/probe/draft"
        try:
            resp = await ctx.http.post(
                url,
                json={
                    "correlation_id": ctx.correlation_id,
                    "lead_id": lead_id,
                    "dry_run": ctx.dry_run,
                },
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "X-Probe-Correlation-Id": ctx.correlation_id,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                name=self.name,
                status=StageStatus.FAILED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail=f"drafter unreachable: {type(exc).__name__}: {exc}",
            )

        if resp.status_code >= 400:
            return StageResult(
                name=self.name,
                status=StageStatus.FAILED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail=f"drafter returned {resp.status_code}: {resp.text[:200]}",
            )

        body = {}
        with contextlib.suppress(Exception):
            body = resp.json()
        draft = (body.get("draft") or "").strip()
        if not draft:
            return StageResult(
                name=self.name,
                status=StageStatus.FAILED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail="drafter response empty",
                facts={"raw_body": str(body)[:200]},
            )
        if draft.startswith("[LLM unavailable"):
            return StageResult(
                name=self.name,
                status=StageStatus.FAILED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail=(
                    "drafter returned the [LLM unavailable] sentinel — check "
                    "Anthropic credits or bridge-mode DeepInfra config"
                ),
                facts={"provider": body.get("provider")},
            )

        ctx.state["draft_body"] = draft
        ctx.state["draft_provider"] = body.get("provider")
        return StageResult(
            name=self.name,
            status=StageStatus.PASSED,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            facts={
                "provider": body.get("provider"),
                "model": body.get("model"),
                "tokens": body.get("token_count"),
                "draft_chars": len(draft),
            },
        )
