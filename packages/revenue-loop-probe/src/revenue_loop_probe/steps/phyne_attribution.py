"""Stage 6 — verify PhyndCRM credited the source agent for the conversion.

This is the final stage of the flywheel contract: money in + attribution
recorded. If this is green, the loop is working end-to-end.
"""

from __future__ import annotations

import asyncio
import time

from ..probe import ProbeContext, ProbeStep, StageResult, StageStatus


class PhyndAttributionStep(ProbeStep):
    name = "phynd.attribution"

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

        lead_id = ctx.state.get("lead_id")
        billing_id = ctx.state.get("dhanam_billing_id")
        if not lead_id or not billing_id:
            return StageResult(
                name=self.name,
                status=StageStatus.SKIPPED,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                detail="lead_id or dhanam_billing_id missing from prior stages",
            )

        timeout_s = float(ctx.env.get("PHYND_ATTRIBUTION_POLL_TIMEOUT_S", "20"))
        deadline = time.perf_counter() + timeout_s
        url = (
            f"{base_url.rstrip('/')}/v1/probe/attribution?lead_id={lead_id}&billing_id={billing_id}"
        )

        assert ctx.http is not None
        last_status: int | None = None
        last_body: str = ""
        while time.perf_counter() < deadline:
            try:
                resp = await ctx.http.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_token}",
                        "X-Probe-Correlation-Id": ctx.correlation_id,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                last_status = -1
                last_body = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(1.0)
                continue

            last_status = resp.status_code
            last_body = resp.text[:200]
            if resp.status_code == 200:
                body = resp.json() if resp.content else {}
                if body.get("credited"):
                    return StageResult(
                        name=self.name,
                        status=StageStatus.PASSED,
                        duration_ms=(time.perf_counter() - t0) * 1000.0,
                        facts={
                            "source_agent": body.get("source_agent"),
                            "credit_amount_mxn_cents": body.get("credit_amount_mxn_cents"),
                            "attribution_id": body.get("attribution_id"),
                        },
                    )
            await asyncio.sleep(1.0)

        return StageResult(
            name=self.name,
            status=StageStatus.FAILED,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
            detail=(
                f"PhyndCRM did not record attribution within {timeout_s:.0f}s "
                f"(last: {last_status} {last_body})"
            ),
        )
