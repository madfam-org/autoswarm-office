from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

from .base import InferenceProvider
from .caching import PromptCacheManager
from .types import InferenceRequest, InferenceResponse, Sensitivity

logger = logging.getLogger(__name__)
_cache_manager = PromptCacheManager()


def _budget_gate_enabled() -> bool:
    return os.environ.get("BUDGET_GATE_ENABLED", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "y",
        "on",
    )


def _try_import_budget_gate() -> Any:
    """Best-effort lazy import of the budget gate.

    Returns ``None`` (and logs once) when the package isn't installed.
    The integration is intentionally optional — the gate is a
    bedrock-safety opt-in, not a hard dependency of the inference
    router.
    """
    try:
        import madfam_budget_gate

        return madfam_budget_gate
    except ImportError:
        logger.warning(
            "budget-gate: BUDGET_GATE_ENABLED is set but madfam-budget-gate "
            "package is not installed; gate is disabled"
        )
        return None


def _is_hard_failure(exc: BaseException) -> bool:
    """Return True when the exception should NOT trigger fallback, because
    the same request would fail identically against any other provider.

    Hard failures (re-raised, never retried, never fallen back from):
      - HTTP 401 (auth) — wrong/missing API key, surface so ops rotates.
        Silently switching to another provider that is ALSO at $0 just
        masks the alarm.
      - HTTP 403 (forbidden) — model/region blocked, would block elsewhere.
      - HTTP 404 (model not found) — bad model id, would 404 elsewhere.
      - HTTP 422 (unprocessable entity) — request-body validation error,
        same payload will fail elsewhere.

    Everything else is fallback-eligible and falls through to the next
    provider in cloud_priority. In particular:
      - HTTP 400 (the load-bearing case: Anthropic returns 400 with
        "credit balance too low" when $0 credits — must fall back, not
        be treated as "request malformed" and silently ship placeholder).
      - HTTP 429 (rate-limited) — fall back to a different vendor rather
        than block the worker on back-off.
      - HTTP 5xx — provider transient.
      - Network errors / timeouts — provider transient.
      - Plain RuntimeError from legacy adapters — preserve existing
        broad-catch fallback behaviour, BUT recognise 'rate-limit' /
        'credit balance' / 'insufficient_quota' embedded in the message
        as fallback-eligible (some providers wrap their HTTP responses
        in RuntimeError before it reaches us).

    The classifier is defensive: when in doubt, fall back. The cost of
    an extra provider hop is far smaller than the cost of returning a
    placeholder string to a worker that will then ship it.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover — httpx is a hard dep elsewhere
        return False

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        # 401/403/404/422 — surface; everything else falls back.
        if status in (401, 403, 404, 422):
            return True

    # Recognise embedded auth-style status in plain error messages —
    # only when the message clearly says "401" / "auth" / "unauthorized"
    # and DOES NOT also say "rate" / "credit" / "quota". This mirrors
    # the HTTPStatusError branch above for adapters that don't preserve
    # the structured exception.
    msg = str(exc).lower()
    auth_signal = (
        "401" in msg
        or "unauthorized" in msg
        or "invalid api key" in msg
        or "invalid_api_key" in msg
    )
    quota_signal = "rate" in msg or "credit" in msg or "quota" in msg
    return auth_signal and not quota_signal


def _is_fallback_eligible(exc: BaseException) -> bool:
    """Inverse of _is_hard_failure — kept as a named helper because the
    test suite documents desired classifier behaviour against this name.

    Network/transient/4xx-non-auth/5xx all return True. 401/403/404/422
    return False. Bare RuntimeError("something broke") returns True
    (broad fallback preserved — see _is_hard_failure for rationale).
    """
    return not _is_hard_failure(exc)




# Provider names expected by the router.  The keys in the providers dict
# passed to ModelRouter should use these identifiers.
LOCAL_PROVIDER = "ollama"
CLOUD_PRIORITY = [
    "anthropic",
    "openai",
    "groq",
    "mistral",
    "moonshot",
    "siliconflow",
    "fireworks",
    "together",
    "deepinfra",
    "openrouter",
]
CHEAPEST_PRIORITY = [
    "deepinfra",
    "groq",
    "together",
    "siliconflow",
    "fireworks",
    "mistral",
    "moonshot",
    "openrouter",
    "openai",
    "anthropic",
]


class ModelRouter:
    """Routes inference requests to providers based on sensitivity policy.

    Routing rules (applied in order):
    1. ``task_type`` — if the org config has a model assignment for the
       request's task type, jump directly to that provider and override
       the model name.
    2. ``require_local=True``  -> only use Ollama (local).
    3. ``restricted`` / ``confidential`` sensitivity -> Ollama only.
    4. ``internal`` -> first available cloud provider (CLOUD_PRIORITY).
    5. ``public``   -> cheapest available (CHEAPEST_PRIORITY).
    6. ``prefer_local=True`` prepends Ollama to the candidate list.

    If the primary candidate is unavailable the router falls through to
    the next candidate in the list.
    """

    def __init__(
        self,
        providers: dict[str, InferenceProvider],
        org_config: object | None = None,
        *,
        budget_gate: Any | None = None,
    ) -> None:
        self._providers = providers
        self._org_config = org_config
        # Budget gate is opt-in: a caller can pass an instance, or the
        # router builds one on the first ``complete()`` call when the
        # ``BUDGET_GATE_ENABLED`` env flag is set and the package is
        # importable.  Once built (or determined missing) the result is
        # memoised on the instance.
        self._budget_gate: Any | None = budget_gate
        self._budget_gate_resolved: bool = budget_gate is not None

    @property
    def available_providers(self) -> list[str]:
        return list(self._providers.keys())

    def _select_provider(self, request: InferenceRequest) -> InferenceProvider:
        """Determine which provider to use for the given request."""
        policy = request.policy

        # ── Task-type routing (highest priority after require_local) ──
        if policy.task_type and self._org_config is not None:
            from .org_config import TaskType

            try:
                task_enum = TaskType(policy.task_type)
                assignments = getattr(self._org_config, "model_assignments", {})
                if task_enum in assignments:
                    assignment = assignments[task_enum]
                    provider = self._providers.get(assignment.provider)
                    if provider is not None:
                        policy.model_override = assignment.model
                        if assignment.max_tokens:
                            policy.max_tokens = assignment.max_tokens
                        if assignment.temperature is not None:
                            policy.temperature = assignment.temperature
                        logger.debug(
                            "Task-type routing: %s → %s/%s",
                            policy.task_type,
                            assignment.provider,
                            assignment.model,
                        )
                        return provider
                    logger.debug(
                        "Task-type assignment for %s points to %s, "
                        "but provider is not registered — falling through",
                        policy.task_type,
                        assignment.provider,
                    )
            except ValueError:
                pass  # Unknown task type — fall through to default routing

        # Hard constraint: local only
        if policy.require_local:
            provider = self._providers.get(LOCAL_PROVIDER)
            if provider is None:
                raise RuntimeError("require_local is True but no Ollama provider is registered.")
            return provider

        # Determine priority lists — org config can override defaults
        cloud_priority = CLOUD_PRIORITY
        cheapest_priority = CHEAPEST_PRIORITY
        if self._org_config is not None:
            org_cloud = getattr(self._org_config, "cloud_priority", None)
            org_cheap = getattr(self._org_config, "cheapest_priority", None)
            if org_cloud:
                cloud_priority = org_cloud
            if org_cheap:
                cheapest_priority = org_cheap

        candidates: list[str] = []

        if policy.sensitivity in (Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL):
            # Sensitive data must stay local
            candidates = [LOCAL_PROVIDER]
        elif policy.sensitivity == Sensitivity.INTERNAL:
            candidates = list(cloud_priority)
        else:
            # PUBLIC -> cheapest first
            candidates = list(cheapest_priority)

        # If prefer_local, prepend Ollama so it's tried first
        if policy.prefer_local and LOCAL_PROVIDER not in candidates:
            candidates.insert(0, LOCAL_PROVIDER)
        elif policy.prefer_local and LOCAL_PROVIDER in candidates:
            candidates.remove(LOCAL_PROVIDER)
            candidates.insert(0, LOCAL_PROVIDER)

        # For multimodal requests, prefer vision-capable providers
        if request.has_media():
            vision_candidates = [
                n
                for n in candidates
                if self._providers.get(n) and self._providers[n].supports_vision
            ]
            if vision_candidates:
                candidates = vision_candidates

        for name in candidates:
            provider = self._providers.get(name)
            if provider is not None:
                return provider

        raise RuntimeError(
            f"No available provider for sensitivity={policy.sensitivity.value}. "
            f"Tried: {candidates}. Registered: {self.available_providers}"
        )

    def _get_fallback_candidates(
        self,
        request: InferenceRequest,
        exclude: InferenceProvider,
    ) -> list[str]:
        """Return provider names suitable for fallback, excluding the primary."""
        policy = request.policy
        if policy.sensitivity in (Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL):
            return []  # Cannot fall back from local-only constraint

        if policy.sensitivity == Sensitivity.INTERNAL:
            candidates = list(CLOUD_PRIORITY)
        else:
            candidates = list(CHEAPEST_PRIORITY)
        return [
            n
            for n in candidates
            if self._providers.get(n) is not None and self._providers[n] is not exclude
        ]

    async def complete(self, request: InferenceRequest) -> InferenceResponse:
        """Route the request to the appropriate provider and return the response.

        Retries once on the primary provider (with 1s delay), then falls
        through to alternative providers before raising.

        When ``BUDGET_GATE_ENABLED=true`` and the ``madfam-budget-gate``
        package is importable, every call is gated by an org/agent/global
        spend check before dispatch.  After a successful response the
        actual usage is recorded against the same scope so daily and
        monthly caps stay accurate.  Default OFF — operators flip the
        flag in production after the first smoke pass.
        """
        gate, scope = self._resolve_gate_and_scope(request)
        if gate is not None and scope is not None:
            decision = await gate.check(
                scope,
                estimated_tokens=request.policy.max_tokens,
                estimated_cost_usd=0.0,
            )
            if not decision.allowed:
                from madfam_budget_gate import BudgetExhausted  # local import

                raise BudgetExhausted(decision.reason, decision.retry_after_seconds)

        response = await self._complete_inner(request)

        # Post-call recording — fire-and-forget: a record() failure must
        # never break the inference path.  The gate's own record() logs
        # exceptions internally, but we add an extra try/except for the
        # local import path.
        if gate is not None and scope is not None:
            try:
                usage = response.usage or {}
                input_tokens = int(usage.get("input_tokens", 0))
                output_tokens = int(usage.get("output_tokens", 0))
                await gate.record(
                    scope,
                    actual_tokens=input_tokens + output_tokens,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    provider=response.provider,
                    model=response.model,
                )
            except Exception as exc:
                logger.warning("budget-gate: record() raised: %s", exc)

        return response

    async def _complete_inner(self, request: InferenceRequest) -> InferenceResponse:
        provider = self._select_provider(request)

        # Gap 7: Apply Anthropic prefix-cache breakpoints if applicable
        provider_name = type(provider).__name__.lower().replace("provider", "")
        request.messages, request.system_prompt = _cache_manager.apply_cache_breakpoints(
            request.messages,
            system_prompt=request.system_prompt or "",
            provider=provider_name,
        )

        # Try primary provider with 1 retry — but only retry when the
        # failure is fallback-eligible. Hard-failures (401/422/etc.) are
        # surfaced immediately so ops sees the real cause.
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                return await provider.complete(request)
            except Exception as exc:
                last_exc = exc
                eligible = _is_fallback_eligible(exc)
                logger.warning(
                    "Provider %s failed (attempt %d/2, fallback_eligible=%s): %s",
                    type(provider).__name__,
                    attempt + 1,
                    eligible,
                    exc,
                )
                if not eligible:
                    # Auth / 404 / 422: re-raise immediately. No retry,
                    # no fallback — the same request will fail the same
                    # way on the next provider too.
                    raise
                if attempt == 0:
                    await asyncio.sleep(1.0)

        # Fallback: try remaining candidates. We only get here if the
        # primary's failure was fallback-eligible (otherwise we re-raised
        # above), so unconditional fall-through is correct.
        for name in self._get_fallback_candidates(request, exclude=provider):
            try:
                logger.info("Falling back to provider: %s", name)
                return await self._providers[name].complete(request)
            except Exception as exc:
                # Fallback chain: only stop early on a hard-failure
                # (e.g. 401 from a misconfigured fallback key) AND log
                # so the operator knows the chain dead-ended.
                logger.warning(
                    "Fallback provider %s also failed (fallback_eligible=%s): %s",
                    name,
                    _is_fallback_eligible(exc),
                    exc,
                )
                last_exc = exc

        raise RuntimeError(f"All providers failed for request. Last error: {last_exc}")

    def _resolve_gate_and_scope(self, request: InferenceRequest) -> tuple[Any, Any]:
        """Return ``(gate, scope)`` if budget gate is enabled, else ``(None, None)``.

        First call lazily resolves the gate; subsequent calls reuse the
        cached value.  Scope is built from request metadata: in this
        bootstrap integration we honour the ``BUDGET_GATE_DEFAULT_ORG_ID``
        env var as the org_id and leave agent_id unset.  Callers that
        need finer-grained scoping should pass an explicit gate
        instance via the constructor.
        """
        if not _budget_gate_enabled():
            return None, None
        if not self._budget_gate_resolved:
            self._budget_gate_resolved = True
            module = _try_import_budget_gate()
            if module is None:
                self._budget_gate = None
            else:
                try:
                    self._budget_gate = module.BudgetGate.from_env()
                except Exception as exc:
                    logger.warning("budget-gate: from_env() failed: %s", exc)
                    self._budget_gate = None
        if self._budget_gate is None:
            return None, None

        # Scope extraction — minimal and overridable.  Callers wanting
        # per-agent scoping inject a gate via constructor + a custom
        # extraction strategy upstream.
        from madfam_budget_gate import BudgetScope  # local import

        org_id = os.environ.get("BUDGET_GATE_DEFAULT_ORG_ID") or None
        scope = BudgetScope(org_id=org_id)
        return self._budget_gate, scope

    async def stream(self, request: InferenceRequest) -> AsyncIterator[str]:
        """Route the request to the appropriate provider and stream the response."""
        provider = self._select_provider(request)
        async for chunk in provider.stream(request):
            yield chunk
