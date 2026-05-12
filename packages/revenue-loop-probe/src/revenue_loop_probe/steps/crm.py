"""Stage 1 — create or fetch a synthetic hot lead in PhyndCRM."""

from __future__ import annotations

import contextlib
import time

from ..probe import ProbeContext, ProbeStep, StageResult, StageStatus


class CrmHotLeadStep(ProbeStep):
    """Ensure a synthetic 'hot lead' exists for the probe to drive."""

    name = "crm.hot_lead"

    async def run(self, ctx: ProbeContext) -> StageResult:
        t0 = time.perf_counter()

        base_url = ctx.env.get("PHYND_CRM_API_URL")
        api_token = ctx.env.get("PHYND_CRM_PROBE_TOKEN")
        if not base_url or not api_token:
            return StageResult(
                name=self.name,
                status=StageStatus.SKIPPED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail="PHYND_CRM_API_URL or PHYND_CRM_PROBE_TOKEN not set",
            )

        assert ctx.http is not None
        url = f"{base_url.rstrip('/')}/v1/probe/leads"
        payload = {
            "correlation_id": ctx.correlation_id,
            "dry_run": ctx.dry_run,
            "channel": "synthetic-probe",
            # Pinned test lead — PhyndCRM's /v1/probe/leads endpoint is
            # expected to be idempotent on (tenant, correlation_id).
            "lead": {
                "email": "probe@madfam.io",
                "stage": "hot",
                "score": 0.95,
                "source_agent": "revenue-loop-probe",
            },
        }
        try:
            resp = await ctx.http.post(
                url,
                json=payload,
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
                detail=f"PhyndCRM unreachable: {type(exc).__name__}: {exc}",
            )

        if resp.status_code >= 400:
            return StageResult(
                name=self.name,
                status=StageStatus.FAILED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail=f"PhyndCRM returned {resp.status_code}: {resp.text[:200]}",
            )

        body = {}
        with contextlib.suppress(Exception):
            body = resp.json()
        lead_id = body.get("lead_id") or body.get("id")
        if not lead_id:
            return StageResult(
                name=self.name,
                status=StageStatus.FAILED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail="PhyndCRM response missing lead_id",
                facts={"raw_body": str(body)[:200]},
            )

        ctx.state["lead_id"] = lead_id
        return StageResult(
            name=self.name,
            status=StageStatus.PASSED,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            facts={"lead_id": lead_id, "phynd_status": resp.status_code},
        )
