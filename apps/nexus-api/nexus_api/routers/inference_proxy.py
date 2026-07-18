"""OpenAI-compatible inference proxy — centralised LLM gateway for the MADFAM ecosystem.

Exposes ``/v1/chat/completions`` and ``/v1/embeddings`` so every ecosystem
service (Fortuna, Yantra4D, PhyndCRM, etc.) can route LLM calls through
Selva's ``ModelRouter`` for unified cost optimisation, task-type routing,
fallback, and observability.

External services point their OpenAI SDK ``base_url`` at this proxy and
authenticate with a Bearer token (the shared ``WORKER_API_TOKEN``).
"""

from __future__ import annotations

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


async def _stream_chunks(model_router, request, completion_id: str, user: dict):
    """Yield SSE chunks in OpenAI streaming format, then meter the stream.

    The provider reports final token accounting once, at stream end, via the
    ``on_usage`` callback. We stash it and write the ledger in the ``finally``
    block so a streamed call is billed exactly like a non-streamed one — the
    metering used to be skipped entirely here, which made every streamed call
    free (RFC 0034 gap)."""
    captured: dict[str, Any] = {}
    started = time.monotonic()

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
    """OpenAI-compatible chat completion endpoint."""
    from madfam_inference.types import InferenceRequest, RoutingPolicy, Sensitivity

    model_router = _get_router()

    # Build routing policy
    model_override = body.model if body.model != "auto" else None
    sensitivity = Sensitivity.PUBLIC
    if x_sensitivity:
        with contextlib.suppress(ValueError):
            sensitivity = Sensitivity(x_sensitivity.lower())

    policy = RoutingPolicy(
        sensitivity=sensitivity,
        max_tokens=body.max_tokens or 4096,
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

    # Streaming
    if body.stream:
        return StreamingResponse(
            _stream_chunks(model_router, inference_request, completion_id, user),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # Non-streaming
    start = time.monotonic()
    try:
        response = await model_router.complete(inference_request)
    except RuntimeError as exc:
        logger.error("Inference proxy completion error: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": "Inference service unavailable",
                    "type": "server_error",
                    "code": "provider_error",
                }
            },
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
