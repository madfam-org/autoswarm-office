"""Endpoint smoke-test primitives for deployment gates.

Read-only by design: this module only performs HTTP(S) checks and returns a
``ToolResult`` that fails closed when any endpoint is invalid or unhealthy.
"""

from __future__ import annotations

import ssl
import time
from typing import Any

from ..base import BaseTool, ToolResult
from .http_tools import _build_safe_request_kwargs


class EndpointSmokeCheckTool(BaseTool):
    name = "endpoint_smoke_check"
    description = (
        "Run read-only HTTP(S) smoke checks against deployment endpoints. "
        "Fails closed on validation errors, request failures, unexpected status, "
        "or response body assertion mismatches."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "endpoints": {
                    "type": "array",
                    "description": "Endpoint checks to run sequentially.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Stable check label."},
                            "url": {"type": "string", "description": "HTTP(S) URL to check."},
                            "method": {
                                "type": "string",
                                "enum": ["GET", "HEAD", "POST"],
                                "default": "GET",
                            },
                            "headers": {"type": "object", "default": {}},
                            "body": {"description": "Optional POST body, string or JSON object."},
                            "expected_statuses": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Allowed status codes. Empty means any 2xx or 3xx.",
                                "default": [],
                            },
                            "body_contains": {
                                "type": "string",
                                "description": "Optional substring that must appear in the response body.",
                                "default": "",
                            },
                            "body_not_contains": {
                                "type": "string",
                                "description": "Optional substring that must not appear in the response body.",
                                "default": "",
                            },
                            "timeout": {"type": "number", "default": 10},
                        },
                        "required": ["url"],
                    },
                },
                "default_timeout": {"type": "number", "default": 10},
            },
            "required": ["endpoints"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import httpx

        endpoints = kwargs.get("endpoints") or []
        default_timeout = float(kwargs.get("default_timeout") or 10)
        if not isinstance(endpoints, list) or not endpoints:
            return ToolResult(success=False, error="endpoints must be a non-empty list")

        checks: list[dict[str, Any]] = []
        transport = httpx.AsyncHTTPTransport(retries=0)
        async with httpx.AsyncClient(transport=transport, trust_env=False) as client:
            for index, endpoint in enumerate(endpoints):
                check = await _run_endpoint_check(client, endpoint, index, default_timeout)
                checks.append(check)

        failed = [c for c in checks if c["verdict"] != "passed"]
        verdict = "blocked" if failed else "passed"
        return ToolResult(
            success=not failed,
            output=f"{verdict}: {len(checks) - len(failed)}/{len(checks)} endpoint smoke check(s) passed",
            data={
                "verdict": verdict,
                "checks": checks,
                "failed_count": len(failed),
                "passed_count": len(checks) - len(failed),
            },
        )


async def _run_endpoint_check(
    client: Any,
    endpoint: Any,
    index: int,
    default_timeout: float,
) -> dict[str, Any]:
    if not isinstance(endpoint, dict):
        return _failed_check(index, "", "endpoint check must be an object")

    name = str(endpoint.get("name") or f"endpoint_{index + 1}")
    url = str(endpoint.get("url") or "")
    method = str(endpoint.get("method") or "GET").upper()
    if method not in {"GET", "HEAD", "POST"}:
        return _failed_check(index, name, f"method {method!r} is not allowed")
    if not url:
        return _failed_check(index, name, "url is required")

    headers = endpoint.get("headers") or {}
    if not isinstance(headers, dict):
        return _failed_check(index, name, "headers must be an object")

    extra: dict[str, Any] = {"timeout": float(endpoint.get("timeout") or default_timeout)}
    if method == "POST" and endpoint.get("body") is not None:
        body = endpoint.get("body")
        if isinstance(body, dict):
            extra["json"] = body
        else:
            extra["content"] = str(body)

    try:
        request_kwargs, original_url = _build_safe_request_kwargs(method, url, headers, extra=extra)
    except ValueError as exc:
        return _failed_check(index, name, f"URL validation failed: {exc}", url=url)

    started = time.perf_counter()
    try:
        response = await client.request(**request_kwargs)
    except ssl.SSLError as exc:
        return _failed_check(index, name, f"TLS verification failed: {exc}", url=original_url)
    except Exception as exc:
        return _failed_check(index, name, f"request failed: {exc}", url=original_url)

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    body_text = response.text[:50000] if method != "HEAD" else ""
    expected_statuses = endpoint.get("expected_statuses") or []
    if expected_statuses:
        status_ok = response.status_code in {int(s) for s in expected_statuses}
    else:
        status_ok = 200 <= response.status_code < 400

    failures: list[str] = []
    if not status_ok:
        failures.append(f"unexpected status {response.status_code}")

    body_contains = str(endpoint.get("body_contains") or "")
    if body_contains and body_contains not in body_text:
        failures.append("body_contains assertion failed")

    body_not_contains = str(endpoint.get("body_not_contains") or "")
    if body_not_contains and body_not_contains in body_text:
        failures.append("body_not_contains assertion failed")

    return {
        "name": name,
        "url": original_url,
        "method": method,
        "status_code": response.status_code,
        "elapsed_ms": elapsed_ms,
        "verdict": "failed" if failures else "passed",
        "failures": failures,
        "response_excerpt": body_text[:1000],
        "response_headers": dict(response.headers),
    }


def _failed_check(index: int, name: str, message: str, *, url: str = "") -> dict[str, Any]:
    return {
        "name": name or f"endpoint_{index + 1}",
        "url": url,
        "method": "",
        "status_code": None,
        "elapsed_ms": None,
        "verdict": "failed",
        "failures": [message],
        "response_excerpt": "",
        "response_headers": {},
    }


def get_smoke_tools() -> list[BaseTool]:
    return [EndpointSmokeCheckTool()]
