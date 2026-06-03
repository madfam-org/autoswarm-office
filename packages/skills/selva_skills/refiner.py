"""
SkillRefiner — Gap 1: Skill Self-Improvement Loop

Mimics the Hermes Agent pattern of actively re-testing existing skills between
sessions and invoking the LLM to rewrite degraded or outdated skill logic.

Resolution order per skill:
1. Load the .py file and attempt to call SKILL_ENTRYPOINT() in a subprocess sandbox.
2. If execution fails OR last_validated is > SKILL_REFINE_INTERVAL_DAYS old:
   → Send the broken skill + failure traceback to madfam_inference.
   → Validate the refined output in the sandbox. If it fails, retry with error
     context up to max_iterations times.
   → Overwrite the .py file with the refined output.
   → Update SKILL_METADATA["last_validated"].
3. If execution passes and metadata is fresh → skip.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class RefinerMetrics:
    """Accumulated metrics from a refine_all() run."""

    skills_checked: int = 0
    skills_refined: int = 0
    skills_failed: int = 0
    total_iterations: int = 0
    avg_refinement_ms: float = 0.0
    _refinement_durations: list[float] = field(default_factory=list, repr=False)

    def record_refinement(self, duration_ms: float) -> None:
        """Record a single refinement duration and update the running average."""
        self._refinement_durations.append(duration_ms)
        self.avg_refinement_ms = sum(self._refinement_durations) / len(self._refinement_durations)


REFINE_PROMPT = """\
You are an expert Python engineer. A Playbook Skill script has either failed execution \
or its logic is stale. Your task is to produce a corrected, improved version that \
conforms to the Selva agentskills/v1 interface.

## Original Skill Code
```python
{original_code}
```

## Failure Details
{failure_details}

## Requirements
- Output ONLY valid Python. No markdown fences.
- Preserve the original intent described in SKILL_DESCRIPTION.
- Fix the root cause of the failure.
- Define: SKILL_DESCRIPTION (str), SKILL_METADATA (dict with key "last_validated"),
  SKILL_VERSION, SKILL_AUTHOR, SKILL_TAGS (list), SKILL_SCHEMA_VERSION = "agentskills/v1",
  SKILL_ENTRYPOINT (callable accepting *args, **kwargs).
"""


class SkillRefiner:
    """
    Iterates over the skills registry, health-checks each skill, and uses the
    madfam_inference LLM router to rewrite any that are broken or stale.
    """

    def __init__(
        self,
        skills_dir: str | None = None,
        refine_interval_days: int = 7,
        max_iterations: int = 3,
    ) -> None:
        self.skills_dir = Path(
            skills_dir or os.environ.get("SELVA_SKILLS_DIR", "/var/lib/selva/skills")
        )
        self.refine_interval_days = refine_interval_days
        self.max_iterations = max(1, max_iterations)
        self._metrics: RefinerMetrics = RefinerMetrics()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def refine_all(self) -> dict[str, str]:
        """
        Iterate every .py skill file and refine if needed.
        Returns a summary dict: {skill_name: "skipped"|"refined"|"failed"|"error"}.
        """
        self._metrics = RefinerMetrics()
        results: dict[str, str] = {}
        if not self.skills_dir.exists():
            logger.warning("Skills dir %s does not exist — nothing to refine.", self.skills_dir)
            return results

        for path in sorted(self.skills_dir.glob("*.py")):
            if path.name.startswith("__"):
                continue
            self._metrics.skills_checked += 1
            try:
                result = self._maybe_refine(path)
                results[path.stem] = result
                if result == "refined":
                    self._metrics.skills_refined += 1
                elif result == "failed":
                    self._metrics.skills_failed += 1
            except Exception as exc:
                logger.error("Unexpected error refining %s: %s", path.name, exc)
                results[path.stem] = "error"
                self._metrics.skills_failed += 1

        return results

    def get_metrics(self) -> RefinerMetrics:
        """Return accumulated metrics from the most recent refine_all() run."""
        return self._metrics

    def refine_one(self, skill_name: str) -> str:
        """Force refinement of a single skill by name (without .py extension)."""
        path = self.skills_dir / f"{skill_name}.py"
        if not path.exists():
            raise FileNotFoundError(f"Skill not found: {path}")
        return self._maybe_refine(path, force=True)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_refine(self, path: Path, force: bool = False) -> str:
        original_code = path.read_text()
        failure_details, passed = self._sandbox_execute(path)

        stale = self._is_stale(original_code)

        if passed and not stale and not force:
            logger.debug("Skill %s is healthy and fresh — skipping.", path.stem)
            return "skipped"

        reason = "forced" if force else ("failed" if not passed else "stale")
        logger.info("Refining skill %s (reason: %s).", path.stem, reason)
        return self._llm_refine(path, original_code, failure_details or "Skill is stale.")

    def _sandbox_execute(self, path: Path) -> tuple[str, bool]:
        """Run SKILL_ENTRYPOINT() in an isolated subprocess. Returns (stderr, passed)."""
        runner = (
            f"import importlib.util, sys\n"
            f"spec = importlib.util.spec_from_file_location('skill', r'{path}')\n"
            f"mod = importlib.util.module_from_spec(spec)\n"
            f"spec.loader.exec_module(mod)\n"
            f"result = mod.SKILL_ENTRYPOINT()\n"
            f"print('OK:', result)\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-c", runner],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if proc.returncode == 0:
                return ("", True)
            return (proc.stderr[:500] or proc.stdout[:500], False)
        except subprocess.TimeoutExpired:
            return ("Execution timed out after 15s.", False)

    def _is_stale(self, code: str) -> bool:
        """Return True if SKILL_METADATA["last_validated"] is older than the interval."""
        try:
            ns: dict = {}
            exec(compile(code, "<skill>", "exec"), ns)  # noqa: S102
            meta = ns.get("SKILL_METADATA", {})
            lv = meta.get("last_validated")
            if lv is None:
                return True
            last = datetime.fromisoformat(str(lv)).replace(tzinfo=UTC)
            return datetime.now(tz=UTC) - last > timedelta(days=self.refine_interval_days)
        except Exception:
            return True

    def _call_llm(self, original_code: str, failure_details: str) -> str:
        """Call the LLM to produce refined skill code. Raises on LLM unavailability."""
        import asyncio

        from madfam_inference import get_default_router  # type: ignore[attr-defined]
        from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity

        request = InferenceRequest(
            messages=[
                {
                    "role": "user",
                    "content": REFINE_PROMPT.format(
                        original_code=original_code,
                        failure_details=failure_details,
                    ),
                }
            ],
            system_prompt=("You are a world-class Python engineer. Output only clean Python code."),
            policy=RoutingPolicy(
                sensitivity=Sensitivity.CONFIDENTIAL,
                task_type="code_generation",
                temperature=0.15,
                max_tokens=2048,
            ),
        )
        router = get_default_router()
        response = asyncio.run(router.complete(request))
        return response.content

    def _llm_refine(self, path: Path, original_code: str, failure_details: str) -> str:
        """Invoke madfam_inference to rewrite the skill with iterative validation.

        After each LLM call, the refined code is sandbox-executed. If sandbox
        validation fails, the LLM is re-invoked with the new error context. This
        repeats up to ``max_iterations`` times. If all iterations fail, the skill
        is marked as ``"failed"`` and the original code is preserved.

        Falls back to stamping last_validated when the LLM is unavailable.
        """
        start_ms = time.monotonic() * 1000
        current_failure = failure_details

        for iteration in range(1, self.max_iterations + 1):
            self._metrics.total_iterations += 1

            try:
                refined_code = self._call_llm(original_code, current_failure)
            except Exception as exc:
                logger.warning("LLM refinement unavailable (%s); stamping last_validated.", exc)
                # Fallback: update the last_validated timestamp so we don't hammer the LLM
                refined_code = original_code.replace(
                    '"last_validated":',
                    f'"last_validated": "{datetime.now(tz=UTC).isoformat()}", "_prev":',
                )
                path.write_text(refined_code)
                duration_ms = time.monotonic() * 1000 - start_ms
                self._metrics.record_refinement(duration_ms)
                logger.info("Skill %s refined (fallback) and written to %s.", path.stem, path)
                return "refined"

            # Write candidate to disk and validate in sandbox
            path.write_text(refined_code)
            sandbox_stderr, passed = self._sandbox_execute(path)

            if passed:
                duration_ms = time.monotonic() * 1000 - start_ms
                self._metrics.record_refinement(duration_ms)
                logger.info(
                    "Skill %s refined successfully on iteration %d and written to %s.",
                    path.stem,
                    iteration,
                    path,
                )
                return "refined"

            logger.warning(
                "Skill %s sandbox validation failed on iteration %d/%d: %s",
                path.stem,
                iteration,
                self.max_iterations,
                sandbox_stderr[:200],
            )
            current_failure = (
                f"Previous refinement attempt (iteration {iteration}) failed.\n"
                f"Error: {sandbox_stderr}"
            )

        # All iterations exhausted — restore original code and mark as failed
        path.write_text(original_code)
        duration_ms = time.monotonic() * 1000 - start_ms
        self._metrics.record_refinement(duration_ms)
        logger.warning(
            "Skill %s failed refinement after %d iterations. Original code restored.",
            path.stem,
            self.max_iterations,
        )
        return "failed"
