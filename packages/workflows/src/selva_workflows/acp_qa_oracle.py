from __future__ import annotations

import asyncio
import logging
import os
import uuid

logger = logging.getLogger(__name__)

SKILL_SYNTHESIS_PROMPT = """\
You are an expert Python engineer. A Clean Swarm agent has successfully reverse-engineered \
the logic of a third-party service. Your task is to synthesize this into a reusable, \
standalone Python skill script that conforms to the Selva agentskills/v1 interface.

## Source Code Produced by the Clean Swarm
```python
{source_code}
```

## Requirements
- Output ONLY valid, runnable Python code. No markdown fences.
- Define exactly these module-level variables (ALL required):
  - `SKILL_SCHEMA_VERSION = "agentskills/v1"`  (literal string, required for interop)
  - `SKILL_VERSION = "1.0.0"`  (semver string)
  - `SKILL_AUTHOR = "selva-qa-oracle"`
  - `SKILL_TAGS: list[str]`  (2-5 relevant tags describing the skill domain)
  - `SKILL_DESCRIPTION: str`  (one clear sentence describing what this skill does)
  - `SKILL_METADATA: dict`  (must include keys: "run_id", "last_validated" as ISO-8601 UTC string)
  - `SKILL_ENTRYPOINT: callable`  (accepts *args, **kwargs, returns a meaningful result)
- Include concise inline comments explaining the key steps.
- The code must be self-contained, importing only stdlib or commonly available packages.
"""


class ACPQAOracleNode:
    """
    Phase IV: The QA Oracle (Validation Loop).

    Validates Phase III output against Phase I black-box tests. On success,
    uses the internal ``madfam_inference`` LLM router to synthesize extracted
    logic into a reusable Python Playbook Skill — directly mirroring the
    Hermes Agent trajectory-compression / continuous-learning loop.
    """

    def __init__(self, source_code: str, test_suite: str) -> None:
        self.source_code = source_code
        self.test_suite = test_suite

    # ------------------------------------------------------------------
    # Skill compilation (Live LLM synthesis)
    # ------------------------------------------------------------------

    async def compile_skill_async(self, run_id: str) -> str | None:
        """
        Invoke the ``madfam_inference`` model router to produce a native
        Python ``.py`` skill from the validated Phase III source code.

        Returns the path of the written skill file, or ``None`` on failure.
        """
        try:
            from madfam_inference.router import ModelRouter
            from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity
        except ImportError:
            logger.warning(
                "[Phase IV] madfam_inference not available; falling back to stub compilation.",
            )
            return self._compile_skill_stub(run_id)

        skills_dir = os.environ.get("SELVA_SKILLS_DIR", "/var/lib/selva/skills")
        os.makedirs(skills_dir, exist_ok=True)

        request = InferenceRequest(
            messages=[
                {
                    "role": "user",
                    "content": SKILL_SYNTHESIS_PROMPT.format(source_code=self.source_code),
                }
            ],
            system_prompt=(
                "You are a world-class Python engineer specialising in autonomous agent tooling. "
                "Output only clean, production-ready Python code — nothing else."
            ),
            policy=RoutingPolicy(
                sensitivity=Sensitivity.CONFIDENTIAL,  # Cleanroom output stays local
                require_local=False,
                task_type="code_generation",
                temperature=0.2,
                max_tokens=2048,
            ),
        )

        try:
            # ModelRouter requires registered providers; we attempt a direct
            # import of the pre-configured singleton if available.
            from madfam_inference import get_default_router  # type: ignore[attr-defined]

            router: ModelRouter = get_default_router()
            response = await router.complete(request)
            skill_code = response.content
        except Exception as exc:
            logger.error("[Phase IV] LLM skill synthesis failed: %s", exc)
            return self._compile_skill_stub(run_id)

        skill_name = f"skill_{run_id.replace('-', '_')}_{uuid.uuid4().hex[:4]}.py"
        filepath = os.path.join(skills_dir, skill_name)

        with open(filepath, "w") as f:
            f.write(skill_code)

        logger.info("[Phase IV] LLM-synthesized skill written to %s", filepath)
        return filepath

    def _compile_skill_stub(self, run_id: str) -> str:
        """Fallback stub writer when the LLM router is unavailable."""
        skills_dir = os.environ.get("SELVA_SKILLS_DIR", "/var/lib/selva/skills")
        os.makedirs(skills_dir, exist_ok=True)

        skill_name = f"skill_{run_id.replace('-', '_')}_{uuid.uuid4().hex[:4]}.py"
        filepath = os.path.join(skills_dir, skill_name)

        stub = (
            f'SKILL_DESCRIPTION = "Stub skill from ACP run: {run_id}"\n'
            f'SKILL_METADATA = {{"run_id": "{run_id}", "synthesized_by": "stub"}}\n\n'
            "def SKILL_ENTRYPOINT(*args, **kwargs):\n"
            f'    return "Stub: logic from run {run_id}"\n'
        )

        with open(filepath, "w") as f:
            f.write(stub)

        logger.info("[Phase IV] Stub skill written to %s", filepath)
        return filepath

    # ------------------------------------------------------------------
    # Primary validation entry-point
    # ------------------------------------------------------------------

    def validate(self, run_id: str = "default-run") -> bool:
        """
        Run Phase I black-box tests against Phase III source, then trigger
        async skill compilation synchronously via ``asyncio.run``.
        """
        logger.info("[Phase IV] Validating Phase III output for run %s …", run_id)

        # ----------------------------------------------------------------
        # Gap 2: Dangerous command approval gate before any sandbox exec
        # ----------------------------------------------------------------
        try:
            from selva_tools.approval import is_dangerous, request_approval

            dangerous, reason = is_dangerous(self.source_code)
            if dangerous:
                logger.warning("[Phase IV] Dangerous pattern detected in source code: %s", reason)
                try:
                    loop = asyncio.get_event_loop()
                    approval = loop.run_until_complete(
                        request_approval(self.source_code[:200], run_id=run_id, reason=reason)
                    )
                except RuntimeError:
                    approval = asyncio.run(
                        request_approval(
                            self.source_code[:200],
                            run_id=run_id,
                            reason=reason,
                        )
                    )
                if not approval.approved:
                    logger.error(
                        "[Phase IV] Dangerous command denied for run %s — aborting.",
                        run_id,
                    )
                    return False
        except ImportError:
            logger.warning("[Phase IV] selva_tools not available — skipping approval gate.")

        # Execute test suite in a sandboxed subprocess if BashTool is available.
        tests_passed = True
        if self.test_suite:
            try:
                from selva_workers.tools.bash_tool import BashTool

                _tool = BashTool(timeout_seconds=60)
                _result = asyncio.run(_tool.execute(self.test_suite))
                tests_passed = _result.return_code == 0
                if not tests_passed:
                    logger.warning(
                        "[Phase IV] Tests failed for run %s (rc=%d): %s",
                        run_id,
                        _result.return_code,
                        _result.stderr[:500],
                    )
            except ImportError:
                logger.warning("[Phase IV] BashTool unavailable — skipping test execution.")
            except Exception:
                logger.warning("[Phase IV] Test execution failed for run %s", run_id, exc_info=True)
                tests_passed = False

        if tests_passed:
            try:
                asyncio.run(self.compile_skill_async(run_id))
            except RuntimeError:
                # Already inside an event loop (e.g., during testing)
                loop = asyncio.get_event_loop()
                loop.run_until_complete(self.compile_skill_async(run_id))

        return tests_passed
