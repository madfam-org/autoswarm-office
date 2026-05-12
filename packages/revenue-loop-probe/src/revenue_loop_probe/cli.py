"""CLI entrypoint: ``revenue-loop-probe``.

Default run is dry-run, reads every known env var, runs all 6 stages,
and prints a JSON report. Exits 0 on pass, 1 on any stage failure.

Flags:
    --live                 Disable dry-run (real side-effects). Confirm prompt.
    --short-circuit        Stop on first failure (default: run all stages).
    --stages a,b,c         Subset of stage names to run (comma-separated).
    --timeout-s N          Global deadline. Default: 120.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

from .probe import ProbeContext, ProbeReport, RevenueLoopProbe
from .steps import (
    CrmHotLeadStep,
    DhanamBillingStep,
    DraftStep,
    EmailSendStep,
    PhyndAttributionStep,
    StripeWebhookStep,
)

KNOWN_ENV_KEYS = (
    "PHYND_CRM_API_URL",
    "PHYND_CRM_PROBE_TOKEN",
    "NEXUS_API_URL",
    "NEXUS_PROBE_TOKEN",
    "DHANAM_STRIPE_WEBHOOK_URL",
    "DHANAM_STRIPE_WEBHOOK_SECRET",
    "DHANAM_API_URL",
    "DHANAM_PROBE_TOKEN",
    "DHANAM_BILLING_POLL_TIMEOUT_S",
    "PHYND_ATTRIBUTION_POLL_TIMEOUT_S",
    "PROBE_PAYMENT_AMOUNT_MXN_CENTS",
)


def default_pipeline():
    return [
        CrmHotLeadStep(),
        DraftStep(),
        EmailSendStep(),
        StripeWebhookStep(),
        DhanamBillingStep(),
        PhyndAttributionStep(),
    ]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="revenue-loop-probe")
    p.add_argument("--live", action="store_true", help="Disable dry-run (real side-effects).")
    p.add_argument("--short-circuit", action="store_true")
    p.add_argument("--stages", default="", help="Comma-separated stage names; default=all.")
    p.add_argument("--timeout-s", type=float, default=120.0)
    p.add_argument(
        "--json-only",
        action="store_true",
        help="Emit only the JSON report on stdout (for pipe consumption).",
    )
    return p


def _select_stages(all_steps, wanted: str):
    if not wanted.strip():
        return all_steps
    names = {n.strip() for n in wanted.split(",") if n.strip()}
    selected = [s for s in all_steps if s.name in names]
    if not selected:
        raise SystemExit(f"--stages matched nothing. Valid names: {[s.name for s in all_steps]}")
    return selected


async def _run(ctx: ProbeContext, steps, *, short_circuit: bool, timeout_s: float):
    probe = RevenueLoopProbe(steps, short_circuit=short_circuit)
    try:
        return await asyncio.wait_for(probe.run(ctx), timeout=timeout_s)
    except asyncio.TimeoutError:
        # Surface as a synthetic failed stage so downstream tooling sees it
        # in the same shape as a real failure.
        from .probe import ProbeReport, StageResult, StageStatus
        import time as _time

        return ProbeReport(
            correlation_id=ctx.correlation_id,
            dry_run=ctx.dry_run,
            started_at=ctx.started_at,
            finished_at=_time.time(),
            stages=[
                StageResult(
                    name="probe.timeout",
                    status=StageStatus.FAILED,
                    duration_ms=timeout_s * 1000.0,
                    detail=f"probe exceeded --timeout-s={timeout_s}",
                )
            ],
        )


async def _upload_report(report: ProbeReport, env: dict[str, str]) -> tuple[bool, str]:
    """Best-effort POST of the report to Nexus /api/v1/probe/runs.

    The probe's exit code must NOT depend on whether Nexus accepted the
    upload — the probe's own stages define success. We log the outcome
    for the CronJob logs but never escalate. selva.town /status renders
    from the most recent successful upload; a failed upload means the
    page stays stale, not that the loop itself is broken.
    """
    base_url = env.get("NEXUS_API_URL")
    token = env.get("NEXUS_PROBE_TOKEN")
    if not base_url or not token:
        return False, "NEXUS_API_URL or NEXUS_PROBE_TOKEN not set — upload skipped"
    url = f"{base_url.rstrip('/')}/api/v1/probe/runs"
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as http:
            resp = await http.post(
                url,
                json=report.to_dict(),
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Probe-Correlation-Id": report.correlation_id,
                },
            )
    except Exception as exc:  # noqa: BLE001
        return False, f"upload failed: {type(exc).__name__}: {exc}"
    if resp.status_code >= 400:
        return False, f"upload returned {resp.status_code}: {resp.text[:160]}"
    return True, "uploaded"


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    env = {k: os.environ[k] for k in KNOWN_ENV_KEYS if os.environ.get(k)}
    ctx = ProbeContext(dry_run=not args.live, env=env)

    all_steps = default_pipeline()
    steps = _select_stages(all_steps, args.stages)

    if args.live and not args.json_only:
        # Small manual confirmation so no one accidentally charges a test lead.
        print(
            "[revenue-loop-probe] --live will fire a real synthetic Stripe event, a real email "
            "send, and a real attribution write. Type 'LIVE' to confirm: ",
            end="",
            flush=True,
        )
        if sys.stdin.readline().strip() != "LIVE":
            print("cancelled.", file=sys.stderr)
            return 2

    report = asyncio.run(
        _run(ctx, steps, short_circuit=args.short_circuit, timeout_s=args.timeout_s)
    )

    # Upload to Nexus for the selva.town /status page. Best-effort — the
    # probe's exit code reflects loop health, not Nexus availability.
    uploaded, upload_detail = asyncio.run(_upload_report(report, env))

    report_dict = report.to_dict()
    report_dict["_upload"] = {"ok": uploaded, "detail": upload_detail}
    print(json.dumps(report_dict, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
