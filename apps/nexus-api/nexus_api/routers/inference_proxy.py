"""OpenAI-compatible inference proxy — centralised LLM gateway for the MADFAM ecosystem.

Exposes ``/v1/chat/completions`` and ``/v1/embeddings`` so every ecosystem
service (Fortuna, Yantra4D, PhyndCRM, etc.) can route LLM calls through
Selva's ``ModelRouter`` for unified cost optimisation, task-type routing,
fallback, and observability.

External services point their OpenAI SDK ``base_url`` at this proxy and
authenticate with a Bearer token (the shared ``WORKER_API_TOKEN``).

Data-handling contract
----------------------
``X-Sensitivity`` is MANDATORY and fails CLOSED: a request without the
header, or with a value outside the enum, is rejected with 400. It used
to default to ``public`` (and to swallow an invalid value silently),
which made "the cheapest cloud vendor" the failure mode for a dropped
header. See ``docs/DATA_CONTRACT_RESTRICTED.md``.

Neither prompts nor completions are persisted or logged anywhere in this
module: the usage ledger stores token counts and USD only, and every log
line below carries routing metadata (org, task type, sensitivity) but
never message content.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db, tenant_session
from ..services.inference_usage_ledger import record_inference_usage

logger = logging.getLogger(__name__)

router = APIRouter(tags=["inference-proxy"])

# ── Request / Response schemas (OpenAI-compatible) ─────────────────────


class ChatMessage(BaseModel):
    role: str
    content: Any  # str or list[dict] for multimodal
    name: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[dict[str, Any]]
    temperature: float | None = None
    max_tokens: int | None = Field(None, le=32768)
    stream: bool = False
    tools: list[dict] | None = None
    response_format: dict[str, Any] | None = None
    top_p: float | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    stop: list[str] | str | None = None


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = "text-embedding-3-small"
    encoding_format: str = "float"


# ── Lazy router singleton ──────────────────────────────────────────────

_router_instance = None


def _get_router():
    """Lazily build and cache a ModelRouter for the proxy."""
    global _router_instance  # noqa: PLW0603
    if _router_instance is not None:
        return _router_instance

    from madfam_inference.factory import build_router_from_env

    from ..config import get_settings

    settings = get_settings()
    _router_instance = build_router_from_env(
        org_config_path=settings.org_config_path,
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        openrouter_api_key=settings.openrouter_api_key,
        together_api_key=settings.together_api_key,
        fireworks_api_key=settings.fireworks_api_key,
        deepinfra_api_key=settings.deepinfra_api_key,
        siliconflow_api_key=settings.siliconflow_api_key,
        moonshot_api_key=settings.moonshot_api_key,
        groq_api_key=getattr(settings, "groq_api_key", None),
        mistral_api_key=getattr(settings, "mistral_api_key", None),
        ollama_base_url=settings.ollama_base_url,
    )
    logger.info(
        "Inference proxy router built with providers: %s",
        ", ".join(_router_instance.available_providers),
    )
    return _router_instance


# ── Tenant policy + rate limiting ──────────────────────────────────────

_rate_limiter = None


def _get_rate_limiter():
    """Lazily build the process-local tenant rate limiter."""
    global _rate_limiter  # noqa: PLW0603
    if _rate_limiter is None:
        from madfam_inference.tenant_policy import InProcessRateLimiter

        _rate_limiter = InProcessRateLimiter()
    return _rate_limiter


def _get_tenant_policies():
    """Return the loaded :class:`TenantPolicyBook` (cached by the loader)."""
    from madfam_inference.tenant_policy import load_tenant_policies

    return load_tenant_policies()


def _error(status_code: int, message: str, code: str, error_type: str) -> JSONResponse:
    """Build an OpenAI-shaped error body.

    ``message`` is operator-facing and MUST NOT contain prompt text — every
    call site below passes a fixed string plus routing metadata only.
    """
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": error_type, "code": code}},
    )


# ── Helpers ────────────────────────────────────────────────────────────


def _make_completion_id() -> str:
    return f"chatcmpl-{uuid.uuid4().hex[:24]}"


def _normalize_usage(usage: dict[str, int] | None) -> dict[str, int]:
    """Map provider usage onto OpenAI wire keys.

    madfam_inference providers normalize usage to ``input_tokens`` /
    ``output_tokens`` (Anthropic-style), while this proxy's ledger writer,
    event emitter, and OpenAI-compatible response body all speak
    ``prompt_tokens`` / ``completion_tokens``. Accept either style so a
    provider that already speaks OpenAI keys stays correct.
    """
    usage = usage or {}
    prompt = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)))
    completion = int(usage.get("output_tokens", usage.get("completion_tokens", 0)))
    total = int(usage.get("total_tokens", 0)) or prompt + completion
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _openai_response(
    completion_id: str,
    content: str,
    model: str,
    usage: dict[str, int],
    tool_calls: list[dict] | None = None,
    finish_reason: str = "stop",
) -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": message,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


async def _record_stream_usage(user: dict, captured: dict) -> None:
    """Write the durable USD-priced ledger row for a completed stream.

    A StreamingResponse outlives the request scope, so the request's
    ``get_db`` session is closed by the time the stream ends — we open a
    fresh ``tenant_session`` scoped to the caller's org. Fail-SAFE: a write
    error degrades to 'spend not recorded', never breaks the response
    (which has already flushed to the client by now anyway).
    """
    usage = _normalize_usage(captured.get("usage"))
    if usage["total_tokens"] <= 0:
        return
    org_id = user.get("org_id", "platform")
    try:
        async with tenant_session(org_id=org_id) as db:
            await record_inference_usage(
                db,
                org_id=org_id,
                caller=user.get("sub", "unknown"),
                provider=captured.get("provider") or "unknown",
                model=captured.get("model"),
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
            )
            await db.commit()
        _emit_proxy_event(
            user,
            captured.get("provider") or "unknown",
            captured.get("model") or "auto",
            usage,
            captured.get("duration_ms", 0),
        )
    except Exception:
        logger.warning(
            "Streaming usage ledger write failed (spend for this call not recorded)",
            exc_info=True,
        )


async def _stream_chunks(
    model_router,
    request,
    completion_id: str,
    user: dict,
    *,
    timeout_seconds: float | None = None,
):
    """Yield SSE chunks in OpenAI streaming format, then meter the stream.

    The provider reports final token accounting once, at stream end, via the
    ``on_usage`` callback. We stash it and write the ledger in the ``finally``
    block so a streamed call is billed exactly like a non-streamed one — the
    metering used to be skipped entirely here, which made every streamed call
    free (RFC 0034 gap).

    ``timeout_seconds`` bounds the WHOLE stream, not each chunk: a provider
    that stalls mid-response would otherwise hold the connection open for
    its own (300 s for Ollama) timeout. On expiry the stream is closed with
    an error chunk and ``[DONE]`` so the client sees a clean end rather than
    a dangling socket, and whatever tokens the provider did report are still
    metered by the ``finally`` block below."""
    captured: dict[str, Any] = {}
    started = time.monotonic()
    deadline = None if timeout_seconds is None else started + timeout_seconds

    def _on_usage(su) -> None:
        # su is madfam_inference.types.StreamUsage
        captured["usage"] = {
            "input_tokens": su.input_tokens,
            "output_tokens": su.output_tokens,
        }
        captured["provider"] = su.provider
        captured["model"] = su.model

    try:
        async for text_chunk in model_router.stream(request, on_usage=_on_usage):
            if deadline is not None and time.monotonic() > deadline:
                logger.error(
                    "Streaming inference exceeded the %.1fs deadline; closing the stream",
                    timeout_seconds,
                )
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "error": {
                                "message": (
                                    f"Inference timed out after {timeout_seconds:.0f}s."
                                ),
                                "type": "server_error",
                                "code": "inference_timeout",
                            }
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"
                return
            chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": request.policy.model_override or "auto",
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": text_chunk},
                        "finish_reason": None,
                    }
                ],
            }
            yield f"data: {json.dumps(chunk)}\n\n"
        # Final chunk with finish_reason
        final = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": request.policy.model_override or "auto",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        logger.error("Streaming error: %s", exc, exc_info=True)
        error_chunk = {
            "error": {
                "message": "Streaming error occurred",
                "type": "server_error",
                "code": "internal_error",
            }
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"
    finally:
        # Meter whatever the stream produced — including a partial stream that
        # errored after some tokens, as long as the provider reported usage.
        if captured.get("usage"):
            captured["duration_ms"] = int((time.monotonic() - started) * 1000)
            await _record_stream_usage(user, captured)


def _emit_proxy_event(
    user: dict,
    provider: str,
    model: str,
    usage: dict[str, int],
    duration_ms: int,
) -> None:
    """Fire-and-forget consumption event (the activity-stream / observability
    record). The DURABLE, USD-priced billing record is written separately by
    `_record_usage` (RFC 0034 P1) — this stays best-effort by design."""
    try:
        from ..service_tracking import emit_proxy_usage

        emit_proxy_usage(
            caller=user.get("sub", "unknown"),
            provider=provider,
            model=model,
            usage=usage,
            duration_ms=duration_ms,
        )
    except Exception:
        logger.debug("Proxy event emission failed", exc_info=True)


async def _record_usage(
    db: AsyncSession,
    user: dict,
    provider: str,
    model: str,
    usage: dict[str, int],
) -> None:
    """Write the durable, USD-priced, org-attributed inference-usage ledger
    entry (RFC 0034 P1). Fail-SAFE not fail-open: a write error is logged at
    WARNING and the call degrades to 'spend not recorded for this call' — it is
    never silently dropped like the old event emit, and it never fails the
    user's inference response."""
    try:
        await record_inference_usage(
            db,
            org_id=user.get("org_id", "platform"),
            caller=user.get("sub", "unknown"),
            provider=provider,
            model=model,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
        await db.commit()
    except Exception:
        logger.warning(
            "Inference usage ledger write failed (spend for this call not recorded)",
            exc_info=True,
        )
        with contextlib.suppress(Exception):
            await db.rollback()


# ── Endpoints ──────────────────────────────────────────────────────────


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    x_task_type: str | None = Header(None, alias="X-Task-Type"),
    x_sensitivity: str | None = Header(None, alias="X-Sensitivity"),
):
    """OpenAI-compatible chat completion endpoint.

    ``X-Sensitivity`` is required. Absent or invalid ⇒ 400: the header is
    the only thing that tells the gateway whether a payload may leave the
    perimeter, so guessing it is not an option.
    """
    from madfam_inference.tenant_policy import apply_floor
    from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity

    org_id = user.get("org_id", "platform")

    # ── 1. Sensitivity: mandatory, fail CLOSED ─────────────────────────
    raw_sensitivity = (x_sensitivity or "").strip()
    valid_levels = ", ".join(level.value for level in Sensitivity)
    if not raw_sensitivity:
        # No prompt text in this log line — only routing metadata.
        logger.warning(
            "Inference rejected: missing X-Sensitivity header (org=%s, task_type=%s)",
            org_id,
            x_task_type or "-",
        )
        return _error(
            400,
            (
                "Missing required header 'X-Sensitivity'. Declare the data "
                f"classification of this request; one of: {valid_levels}."
            ),
            "missing_sensitivity",
            "invalid_request_error",
        )
    try:
        sensitivity = Sensitivity(raw_sensitivity.lower())
    except ValueError:
        # Echo the rejected value: it is a routing label chosen by the
        # caller's code, never user or prompt content.
        logger.warning(
            "Inference rejected: invalid X-Sensitivity=%r (org=%s, task_type=%s)",
            raw_sensitivity,
            org_id,
            x_task_type or "-",
        )
        return _error(
            400,
            (
                f"Invalid 'X-Sensitivity' value {raw_sensitivity!r}. "
                f"Must be one of: {valid_levels}."
            ),
            "invalid_sensitivity",
            "invalid_request_error",
        )

    # ── 2. Tenant policy: floor, task-type allowlist, caps, rate limit ─
    policies = _get_tenant_policies()
    tenant_policy = policies.for_org(org_id)

    if tenant_policy is not None:
        floored = apply_floor(sensitivity, tenant_policy.sensitivity_floor)
        if floored is not sensitivity:
            logger.info(
                "Tenant %s: sensitivity raised %s → %s by tenant floor",
                org_id,
                sensitivity.value,
                floored.value,
            )
            sensitivity = floored

        if (
            tenant_policy.allowed_task_types
            and x_task_type
            and x_task_type not in tenant_policy.allowed_task_types
        ):
            logger.warning(
                "Inference rejected: task_type=%s not allowed for tenant %s",
                x_task_type,
                org_id,
            )
            return _error(
                400,
                (
                    f"Task type {x_task_type!r} is not permitted for this tenant. "
                    f"Allowed: {', '.join(tenant_policy.allowed_task_types)}."
                ),
                "task_type_not_allowed",
                "invalid_request_error",
            )

        allowed, retry_after = _get_rate_limiter().check(
            org_id, tenant_policy.rate_limit_per_minute
        )
        if not allowed:
            logger.warning(
                "Inference rate-limited: tenant=%s limit=%s/min",
                org_id,
                tenant_policy.rate_limit_per_minute,
            )
            limited = _error(
                429,
                (
                    "Rate limit exceeded for this tenant "
                    f"({tenant_policy.rate_limit_per_minute} requests/minute per gateway replica)."
                ),
                "tenant_rate_limited",
                "rate_limit_error",
            )
            limited.headers["Retry-After"] = str(retry_after)
            return limited

    # ── 3. Build routing policy with tenant-capped limits ──────────────
    # Router construction happens after validation so a rejected request
    # never pays to build (or lazily initialise) the provider set.
    model_router = _get_router()
    model_override = body.model if body.model != "auto" else None
    max_tokens_cap = policies.max_tokens_for(tenant_policy)
    requested_max_tokens = body.max_tokens or max_tokens_cap
    max_tokens = min(requested_max_tokens, max_tokens_cap)

    policy = RoutingPolicy(
        sensitivity=sensitivity,
        max_tokens=max_tokens,
        temperature=body.temperature if body.temperature is not None else 0.7,
        task_type=x_task_type,
        model_override=model_override,
    )

    # Extract system prompt from messages if present
    system_prompt = None
    messages = []
    for msg in body.messages:
        if msg.get("role") == "system":
            system_prompt = msg.get("content", "")
        else:
            messages.append(msg)

    inference_request = InferenceRequest(
        messages=messages,
        policy=policy,
        system_prompt=system_prompt,
        tools=body.tools,
        response_format=body.response_format,
    )

    completion_id = _make_completion_id()
    timeout_seconds = policies.timeout_for(tenant_policy)

    # Streaming
    if body.stream:
        return StreamingResponse(
            _stream_chunks(
                model_router,
                inference_request,
                completion_id,
                user,
                timeout_seconds=timeout_seconds,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming, under a server-side deadline. Without this the worst
    # case for a restricted call was the Ollama provider timeout (300 s)
    # plus a retry — over ten minutes of a human staring at a spinner.
    start = time.monotonic()
    try:
        response = await asyncio.wait_for(
            model_router.complete(inference_request), timeout=timeout_seconds
        )
    except TimeoutError:
        logger.error(
            "Inference proxy timed out after %.1fs (org=%s, sensitivity=%s, task_type=%s)",
            timeout_seconds,
            org_id,
            sensitivity.value,
            x_task_type or "-",
        )
        return _error(
            504,
            f"Inference timed out after {timeout_seconds:.0f}s.",
            "inference_timeout",
            "server_error",
        )
    except RuntimeError as exc:
        # The message is the router's own diagnostic (provider names and
        # error classes) — it never contains prompt content.
        logger.error(
            "Inference proxy completion error (org=%s, sensitivity=%s): %s",
            org_id,
            sensitivity.value,
            exc,
        )
        if sensitivity in (Sensitivity.RESTRICTED, Sensitivity.CONFIDENTIAL):
            # Fail-closed by design: regulated data may only be served by
            # the local backend, so "no local backend" is an outage, never
            # a reason to reach for a cloud vendor.
            return _error(
                503,
                (
                    f"No local inference backend is available to serve "
                    f"'{sensitivity.value}' data. This request is refused rather "
                    "than routed to a third-party provider. Operator: deploy the "
                    "local model backend and set OLLAMA_BASE_URL "
                    "(see docs/RUNBOOK_SELVA_CTM.md)."
                ),
                "local_backend_unavailable",
                "server_error",
            )
        return _error(
            503,
            "Inference service unavailable",
            "provider_error",
            "server_error",
        )

    duration_ms = int((time.monotonic() - start) * 1000)

    usage = _normalize_usage(response.usage)
    _emit_proxy_event(user, response.provider, response.model, usage, duration_ms)
    await _record_usage(db, user, response.provider, response.model, usage)

    return _openai_response(
        completion_id=completion_id,
        content=response.content,
        model=response.model,
        usage=usage,
        tool_calls=response.tool_calls,
    )


@router.post("/embeddings")
async def embeddings(
    body: EmbeddingRequest,
    user: dict = Depends(get_current_user),
):
    """OpenAI-compatible embeddings endpoint."""
    from pathlib import Path

    import httpx

    from madfam_inference.org_config import load_org_config

    from ..config import get_settings

    settings = get_settings()

    try:
        org_config = load_org_config(Path(settings.org_config_path).expanduser())
    except Exception:
        from madfam_inference.org_config import OrgConfig

        org_config = OrgConfig()

    # Determine which provider handles embeddings
    embedding_provider = org_config.embedding_provider  # "openai" by default
    embedding_model = body.model or org_config.embedding_model

    # Resolve the API key for the embedding provider
    provider_key_map = {
        "openai": settings.openai_api_key,
        "deepinfra": settings.deepinfra_api_key,
        "together": settings.together_api_key,
        "fireworks": settings.fireworks_api_key,
    }
    provider_url_map = {
        "openai": "https://api.openai.com/v1/embeddings",
        "deepinfra": "https://api.deepinfra.com/v1/openai/embeddings",
        "together": "https://api.together.xyz/v1/embeddings",
        "fireworks": "https://api.fireworks.ai/inference/v1/embeddings",
    }

    api_key = provider_key_map.get(embedding_provider)
    endpoint = provider_url_map.get(embedding_provider)

    if not api_key or not endpoint:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": f"Embedding provider '{embedding_provider}' not configured",
                    "type": "server_error",
                    "code": "no_embedding_provider",
                }
            },
        )

    texts = body.input if isinstance(body.input, list) else [body.input]
    if len(texts) > 256:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "message": "Maximum 256 inputs per request",
                    "type": "invalid_request_error",
                    "code": "too_many_inputs",
                }
            },
        )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": embedding_model,
                    "encoding_format": body.encoding_format,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.error("Embedding request failed: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "message": "Embedding service unavailable",
                    "type": "server_error",
                    "code": "embedding_error",
                }
            },
        )
