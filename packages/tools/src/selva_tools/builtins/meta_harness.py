"""Meta-Harness integration tools (wraps tezca/experiments/meta-harness).

Per the 2026-04-17 memory (``project_meta_harness``), the Phase 0 spike at
``tezca/experiments/meta-harness/`` ships a HITL budget gate, Selva-routed
LLM client, and a gated runner CLI. These tools expose that harness to
Selva agents so they can (1) check a run's estimated cost before committing
spend, (2) route inference through the same gate the harness uses, and
(3) introspect the 9-role manifesto state for multi-role ensemble work.

**STUB STATUS:** The upstream harness is still Phase 0 — its public Python
API is narrow (``meta_harness_madfam.runner`` exposes an argparse CLI, not
a stable library surface). Rather than invent APIs that do not exist, these
tools shell out to the ``meta-harness-madfam`` CLI via subprocess with a
pinned set of flags. Role-summary / convergence-check / submit-round /
escalate-tier are scaffolded against a future harness surface (marked
``stub=True`` in the response data) and will be rewritten once the
harness stabilises and exposes a proper SDK. Budget-gate + route are
functional today because they wrap the existing ``estimate`` CLI and the
``SelvaClient`` env-var contract.

Configuration:

- ``META_HARNESS_DIR`` — absolute path to the harness checkout
  (default: ``/Users/aldoruizluna/labspace/tezca/experiments/meta-harness``).
  Overridden in prod via ConfigMap. When absent the tools return a
  structured error rather than crashing.
- ``META_HARNESS_PYTHON`` — python interpreter used for CLI invocation
  (default: ``{META_HARNESS_DIR}/.venv/bin/python`` if present, else ``python3``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shlex
import sys
from pathlib import Path
from typing import Any

from ..audience import Audience
from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

DEFAULT_HARNESS_DIR = "/Users/aldoruizluna/labspace/tezca/experiments/meta-harness"
CLI_TIMEOUT_SEC = 30


def _harness_dir() -> Path:
    raw_dir = Path(os.environ.get("META_HARNESS_DIR", DEFAULT_HARNESS_DIR)).expanduser()
    if not raw_dir.is_absolute():
        raise ValueError("META_HARNESS_DIR must be an absolute path")

    resolved_dir = raw_dir.resolve()
    if not resolved_dir.is_dir():
        raise FileNotFoundError(f"harness directory not found: {resolved_dir}")

    allowlist_csv = os.environ.get("META_HARNESS_DIR_ALLOWLIST")
    if allowlist_csv:
        allowed = {
            Path(path).expanduser().resolve()
            for path in allowlist_csv.split(",")
            if path.strip()
        }
        if resolved_dir not in allowed:
            raise ValueError(f"harness directory not in allow-list: {resolved_dir}")

    return resolved_dir


def _python_executable(harness_dir: Path) -> str:
    override = os.environ.get("META_HARNESS_PYTHON")
    if override:
        override_path = Path(override)
        if not override_path.is_absolute():
            raise ValueError(
                "META_HARNESS_PYTHON must be an absolute executable path when set"
            )
        if not override_path.exists():
            raise FileNotFoundError(f"interpreter not found: {override_path}")
        return str(override_path)
    venv_py = harness_dir / ".venv" / "bin" / "python"
    if venv_py.exists():
        return str(venv_py)
    return sys.executable


async def _run_cli(args: list[str]) -> tuple[int, str, str]:
    """Run the meta-harness CLI. Returns (returncode, stdout, stderr)."""
    try:
        harness_dir = _harness_dir()
        py = _python_executable(harness_dir)
    except (FileNotFoundError, ValueError) as exc:
        return 127, "", str(exc)
    cmd = [py, "-m", "meta_harness_madfam.runner", *args]
    env = {
        **os.environ,
        "PYTHONPATH": str(harness_dir / "src"),
    }
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(harness_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=CLI_TIMEOUT_SEC)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return 124, "", f"timed out after {CLI_TIMEOUT_SEC}s: {shlex.join(cmd)}"
        return (
            proc.returncode if proc.returncode is not None else -1,
            stdout_b.decode("utf-8", errors="replace"),
            stderr_b.decode("utf-8", errors="replace"),
        )
    except FileNotFoundError as e:
        return 127, "", f"interpreter not found: {e}"
    except Exception as e:
        logger.error("meta-harness CLI invocation failed: %s", e)
        return -1, "", str(e)


class MetaHarnessBudgetGateTool(BaseTool):
    """Pre-run budget gate — evaluate a run shape's estimated cost."""

    name = "meta_harness_budget_gate"
    description = (
        "Evaluate a Meta-Harness run shape's estimated worst-case USD cost "
        "and decide if it should be allowed, escalated to ASK, or denied "
        "against the agent tier's budget ceiling. Reads the harness "
        "``estimate`` subcommand (no spend occurs). Useful before any "
        "inference-heavy operation so the agent can self-gate. Tiers: "
        "'allow' below $1, 'ask' up to hard_cap_usd (default $10), "
        "'deny' above hard_cap_usd."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "iterations": {"type": "integer", "minimum": 1},
                "candidates_per_iteration": {"type": "integer", "minimum": 1},
                "eval_set_size": {"type": "integer", "minimum": 1},
                "input_tokens_per_eval": {"type": "integer", "minimum": 1},
                "output_tokens_per_eval": {"type": "integer", "minimum": 1},
                "agent_tier": {
                    "type": "string",
                    "enum": ["ask", "ask_quiet", "allow_shadow", "allow"],
                    "default": "ask",
                },
                "hard_cap_usd": {"type": "number", "default": 10.0},
            },
            "required": [
                "model",
                "iterations",
                "candidates_per_iteration",
                "eval_set_size",
                "input_tokens_per_eval",
                "output_tokens_per_eval",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            args = [
                "estimate",
                "--model",
                str(kwargs["model"]),
                "--iterations",
                str(int(kwargs["iterations"])),
                "--candidates",
                str(int(kwargs["candidates_per_iteration"])),
                "--eval-set-size",
                str(int(kwargs["eval_set_size"])),
                "--input-tokens-per-eval",
                str(int(kwargs["input_tokens_per_eval"])),
                "--output-tokens-per-eval",
                str(int(kwargs["output_tokens_per_eval"])),
                "--json",
            ]
            rc, stdout, stderr = await _run_cli(args)
            if rc != 0:
                return ToolResult(
                    success=False,
                    error=f"harness estimate failed (rc={rc}): {stderr.strip() or stdout.strip()}",
                )
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as e:
                return ToolResult(
                    success=False,
                    error=f"could not parse estimate JSON: {e}",
                )
            total_usd = float((parsed.get("estimate") or {}).get("total_usd", 0.0))
            hard_cap = float(kwargs.get("hard_cap_usd", 10.0))
            tier = str(kwargs.get("agent_tier", "ask")).lower()
            # Decision table: tier + usd → allow/ask/deny.
            if total_usd > hard_cap:
                decision = "deny"
            elif total_usd < 1.0 and tier in ("allow", "allow_shadow"):
                decision = "allow"
            else:
                decision = "ask"
            return ToolResult(
                success=True,
                output=(
                    f"decision={decision} total_usd=${total_usd:.4f} "
                    f"cap=${hard_cap:.2f} tier={tier}"
                ),
                data={
                    "decision": decision,
                    "total_usd": total_usd,
                    "hard_cap_usd": hard_cap,
                    "agent_tier": tier,
                    "estimate": parsed.get("estimate"),
                    "run": parsed.get("run"),
                },
            )
        except Exception as e:
            logger.error("meta_harness_budget_gate failed: %s", e)
            return ToolResult(success=False, error=str(e))


class MetaHarnessRouteTool(BaseTool):
    """Return the Selva routing config the harness will use for a given run."""

    name = "meta_harness_route"
    description = (
        "Resolve which inference provider + base URL the Meta-Harness "
        "SelvaClient would use for a request, without making a network "
        "call. Reads the same env var contract the harness uses "
        "(``MADFAM_INFERENCE_PROVIDER``, ``SELVA_API_BASE``, "
        "``SELVA_API_KEY``, ``DEEPINFRA_API_KEY``). Useful for the agent "
        "to confirm 'is my next inference call going through Selva or the "
        "DeepInfra bridge?' before dispatching an expensive run."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prefer_provider": {
                    "type": "string",
                    "enum": ["selva", "deepinfra"],
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            override = (
                kwargs.get("prefer_provider")
                or os.environ.get("MADFAM_INFERENCE_PROVIDER", "").strip().lower()
            )
            if override in ("selva", "deepinfra"):
                provider = override
            elif os.environ.get("SELVA_API_BASE") and os.environ.get("SELVA_API_KEY"):
                provider = "selva"
            elif os.environ.get("DEEPINFRA_API_KEY"):
                provider = "deepinfra"
            else:
                return ToolResult(
                    success=False,
                    error=(
                        "no inference provider configured: set "
                        "MADFAM_INFERENCE_PROVIDER or SELVA_API_BASE+SELVA_API_KEY "
                        "or DEEPINFRA_API_KEY"
                    ),
                )
            if provider == "selva":
                base_url = os.environ.get("SELVA_API_BASE", "")
                has_key = bool(os.environ.get("SELVA_API_KEY"))
            else:
                base_url = os.environ.get(
                    "DEEPINFRA_API_BASE", "https://api.deepinfra.com/v1/openai"
                )
                has_key = bool(os.environ.get("DEEPINFRA_API_KEY"))
            return ToolResult(
                success=True,
                output=f"provider={provider} base_url={base_url} key_present={has_key}",
                data={
                    "provider": provider,
                    "base_url": base_url,
                    "api_key_present": has_key,
                },
            )
        except Exception as e:
            logger.error("meta_harness_route failed: %s", e)
            return ToolResult(success=False, error=str(e))


class MetaHarnessRoleSummaryTool(BaseTool):
    """Summarise the 9-role manifesto state for an agent session (stub)."""

    name = "meta_harness_role_summary"
    description = (
        "Return a summary of the 9-role MADFAM manifesto state for a "
        "given agent session: which roles have spoken, which are silent, "
        "which converged, and which are blocked. STUB: upstream harness "
        "has not yet exposed this surface; current implementation returns "
        "a ``stub=True`` placeholder so downstream composition code can "
        "be developed against the expected contract. Will be wired once "
        "the harness stabilises."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
            },
            "required": ["session_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            session_id = str(kwargs["session_id"])
            harness_dir = _harness_dir()
            if not harness_dir.exists():
                return ToolResult(
                    success=False,
                    error=f"harness directory not found: {harness_dir}",
                )
            # Roles per the manifesto 9-node architecture — stable names
            # consumers can pattern-match on even while the harness API is
            # in flux.
            roles = [
                "brain_trust",
                "build_run",
                "growth_market",
                "phygital_bridge",
                "ledger",
                "orchestration",
                "intelligence",
                "compliance",
                "communications",
            ]
            return ToolResult(
                success=True,
                output=f"role summary for session={session_id} (stub)",
                data={
                    "session_id": session_id,
                    "roles": roles,
                    "roles_spoken": [],
                    "roles_silent": roles,
                    "roles_converged": [],
                    "roles_blocked": [],
                    "stub": True,
                },
            )
        except Exception as e:
            logger.error("meta_harness_role_summary failed: %s", e)
            return ToolResult(success=False, error=str(e))


class MetaHarnessConvergenceCheckTool(BaseTool):
    """Return whether a multi-role ensemble has converged (stub)."""

    name = "meta_harness_convergence_check"
    description = (
        "Return whether a multi-role ensemble for a given session has "
        "converged on a decision. Returns ``converged=True`` when all "
        "required roles have emitted outputs AND pairwise disagreement "
        "is below ``disagreement_threshold``. STUB: returns "
        "``stub=True`` until the harness exposes ensemble state. Safe to "
        "compose against — the returned shape is stable."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "required_roles": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "disagreement_threshold": {
                    "type": "number",
                    "default": 0.2,
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
            },
            "required": ["session_id"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            session_id = str(kwargs["session_id"])
            required = list(kwargs.get("required_roles") or [])
            threshold = float(kwargs.get("disagreement_threshold", 0.2))
            harness_dir = _harness_dir()
            if not harness_dir.exists():
                return ToolResult(
                    success=False,
                    error=f"harness directory not found: {harness_dir}",
                )
            return ToolResult(
                success=True,
                output=(
                    f"convergence check session={session_id} (stub — "
                    f"always False until harness exposes ensemble state)"
                ),
                data={
                    "session_id": session_id,
                    "converged": False,
                    "required_roles": required,
                    "disagreement_threshold": threshold,
                    "missing_roles": required,
                    "stub": True,
                },
            )
        except Exception as e:
            logger.error("meta_harness_convergence_check failed: %s", e)
            return ToolResult(success=False, error=str(e))


class MetaHarnessSubmitRoundTool(BaseTool):
    """Submit an agent round with role metadata into a harness session (stub)."""

    name = "meta_harness_submit_round"
    description = (
        "Submit an agent round (produced content + role + confidence) into "
        "a harness session. STUB: upstream harness does not yet accept "
        "external round submissions — this tool records the intent in the "
        "harness ``approvals/`` directory as an append-only JSON line so "
        "the shape is preserved for future backfill. Once the harness "
        "exposes an ingest endpoint this tool will POST there instead."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "role": {"type": "string"},
                "content": {"type": "string"},
                "confidence": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                },
                "metadata": {"type": "object"},
            },
            "required": ["session_id", "role", "content"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            harness_dir = _harness_dir()
            if not harness_dir.exists():
                return ToolResult(
                    success=False,
                    error=f"harness directory not found: {harness_dir}",
                )
            session_id = str(kwargs["session_id"])
            role = str(kwargs["role"])
            content = str(kwargs["content"])
            confidence = float(kwargs.get("confidence", 0.5))
            metadata = dict(kwargs.get("metadata") or {})
            approvals_dir = harness_dir / "approvals"
            try:
                approvals_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"could not create approvals dir: {e}",
                )
            record = {
                "type": "selva_round_intent",
                "session_id": session_id,
                "role": role,
                "content": content[:5000],
                "confidence": confidence,
                "metadata": metadata,
            }
            try:
                # Append-only JSONL so multiple agents can write safely.
                path = approvals_dir / f"rounds-{session_id}.jsonl"
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"could not append round record: {e}",
                )
            return ToolResult(
                success=True,
                output=(
                    f"recorded round intent for session={session_id} role={role} "
                    f"(stub — not yet forwarded to harness)"
                ),
                data={
                    "session_id": session_id,
                    "role": role,
                    "confidence": confidence,
                    "recorded_path": str(path),
                    "stub": True,
                },
            )
        except Exception as e:
            logger.error("meta_harness_submit_round failed: %s", e)
            return ToolResult(success=False, error=str(e))


class MetaHarnessEscalateTierTool(BaseTool):
    """Request an HITL tier escalation for the current agent session."""

    name = "meta_harness_escalate_tier"
    description = (
        "Request a tier escalation — agent explicitly asks that the next "
        "decision go through ASK (human approval) even if the agent's "
        "current tier would otherwise auto-allow. Writes an intent record "
        "under the harness ``approvals/`` dir so the request is visible to "
        "human reviewers. Does NOT bypass the existing HITL pipeline; it "
        "is purely a signal that the agent wants stricter oversight."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "current_tier": {
                    "type": "string",
                    "enum": ["ask", "ask_quiet", "allow_shadow", "allow"],
                },
                "requested_tier": {
                    "type": "string",
                    "enum": ["ask", "ask_quiet", "allow_shadow", "allow"],
                    "default": "ask",
                },
                "reason": {"type": "string"},
            },
            "required": ["session_id", "current_tier", "reason"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            harness_dir = _harness_dir()
            if not harness_dir.exists():
                return ToolResult(
                    success=False,
                    error=f"harness directory not found: {harness_dir}",
                )
            approvals_dir = harness_dir / "approvals"
            try:
                approvals_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"could not create approvals dir: {e}",
                )
            session_id = str(kwargs["session_id"])
            current = str(kwargs["current_tier"]).lower()
            requested = str(kwargs.get("requested_tier", "ask")).lower()
            reason = str(kwargs["reason"])[:1000]
            # Ordering: only record if the request is strictly stricter or
            # a lateral move. We explicitly refuse to act on a LOOSENING
            # request — that path must go through admin UI, not an agent.
            order = {"allow": 3, "allow_shadow": 2, "ask_quiet": 1, "ask": 0}
            if order.get(requested, -1) > order.get(current, 99):
                return ToolResult(
                    success=False,
                    error=(
                        f"refused: requested tier {requested!r} is looser than current {current!r}"
                    ),
                )
            record = {
                "type": "tier_escalation_request",
                "session_id": session_id,
                "current_tier": current,
                "requested_tier": requested,
                "reason": reason,
            }
            try:
                path = approvals_dir / f"escalations-{session_id}.jsonl"
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            except Exception as e:
                return ToolResult(
                    success=False,
                    error=f"could not append escalation record: {e}",
                )
            return ToolResult(
                success=True,
                output=(
                    f"tier escalation requested: {current} -> {requested} for session={session_id}"
                ),
                data={
                    "session_id": session_id,
                    "current_tier": current,
                    "requested_tier": requested,
                    "reason": reason,
                    "recorded_path": str(path),
                },
            )
        except Exception as e:
            logger.error("meta_harness_escalate_tier failed: %s", e)
            return ToolResult(success=False, error=str(e))


def get_meta_harness_tools() -> list[BaseTool]:
    """Return the Meta-Harness tool set."""
    return [
        MetaHarnessBudgetGateTool(),
        MetaHarnessRouteTool(),
        MetaHarnessRoleSummaryTool(),
        MetaHarnessConvergenceCheckTool(),
        MetaHarnessSubmitRoundTool(),
        MetaHarnessEscalateTierTool(),
    ]


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    MetaHarnessBudgetGateTool,
    MetaHarnessRouteTool,
    MetaHarnessRoleSummaryTool,
    MetaHarnessConvergenceCheckTool,
    MetaHarnessSubmitRoundTool,
    MetaHarnessEscalateTierTool,
):
    _cls.audience = Audience.PLATFORM
