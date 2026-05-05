"""HTTP tools: generic requests, GraphQL queries, and webhook delivery."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import logging
import socket
import ssl
import urllib.parse
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger("autoswarm.http_tools")

# ---------------------------------------------------------------------------
# SSRF protection -- mirrors the gateway.py _validate_webhook_url pattern
# ---------------------------------------------------------------------------
_BLOCKED_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
]


def _is_private_ip(ip: ipaddress._BaseAddress) -> bool:
    """Return True when the address falls in any blocked network."""
    return any(ip in network for network in _BLOCKED_NETWORKS)


def _validate_url(url: str) -> str:
    """Validate a URL to prevent SSRF attacks.

    Checks:
    - Length <= 2048 characters
    - Scheme must be http or https
    - Hostname must resolve to a non-private IP address

    Returns the validated URL, or raises ValueError on failure.

    NOTE: This function performs admission-time validation only. The actual
    HTTP request must use ``_resolve_safe_url`` so that the IP discovered
    here is the IP we connect to, eliminating the DNS-rebinding window
    between validation and connect.
    """
    if len(url) > 2048:
        raise ValueError("URL exceeds maximum length of 2048 characters")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL is missing a hostname")

    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Hostname could not be resolved: {hostname}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_private_ip(ip):
            raise ValueError(f"Hostname resolves to a private/reserved IP address: {hostname}")

    return url


def _resolve_safe_url(url: str) -> tuple[str, str, str]:
    """Resolve URL once, validate the IP, and return a tuple suitable for connecting.

    Returns ``(ip_url, hostname, original_url)`` where:
      - ``ip_url`` has the netloc rewritten to the resolved IP literal so httpx
        connects to the IP we just validated (no second DNS lookup, no rebind).
      - ``hostname`` is the original hostname, intended for the ``Host:`` header
        AND as the SNI hostname for HTTPS.
      - ``original_url`` is the unmodified input, useful for error messages /
        response logging where the user-facing URL should be preserved.

    Raises ``ValueError`` on any validation failure.
    """
    if len(url) > 2048:
        raise ValueError("URL exceeds maximum length of 2048 characters")

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"URL scheme must be http or https, got: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL is missing a hostname")

    try:
        addrinfos = socket.getaddrinfo(hostname, parsed.port or None)
    except socket.gaierror as exc:
        raise ValueError(f"Hostname could not be resolved: {hostname}") from exc

    if not addrinfos:
        raise ValueError(f"Hostname could not be resolved: {hostname}")

    # Use the first resolved address; validate every returned address so that
    # multi-record DNS responses with one private entry still get rejected.
    chosen_ip: str | None = None
    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        # sockaddr[0] is the address string for both AF_INET and AF_INET6;
        # the tuple type is heterogeneous so mypy widens to ``str | int``.
        ip_str = str(sockaddr[0])
        ip_obj = ipaddress.ip_address(ip_str)
        if _is_private_ip(ip_obj):
            raise ValueError(
                f"Hostname resolves to a private/reserved IP address: {hostname}"
            )
        if chosen_ip is None:
            chosen_ip = ip_str

    assert chosen_ip is not None  # validated by len(addrinfos) check above

    # IPv6 literals must be bracketed in the URL netloc.
    is_ipv6 = ":" in chosen_ip
    ip_literal = f"[{chosen_ip}]" if is_ipv6 else chosen_ip
    new_netloc = f"{ip_literal}:{parsed.port}" if parsed.port else ip_literal

    ip_url = parsed._replace(netloc=new_netloc).geturl()
    return ip_url, hostname, url


def _build_safe_request_kwargs(
    method: str,
    url: str,
    headers: dict[str, str],
    *,
    extra: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """Build request kwargs that connect to the validated IP with SNI preserved.

    Returns ``(request_kwargs, original_url)``. The kwargs include the rewritten
    URL, a ``Host`` header pointing at the original hostname, and an
    ``extensions={"sni_hostname": ...}`` entry so HTTPS cert verification works
    against the original hostname even though we connect to the IP literal.

    Also injects the W3C ``traceparent`` (and ``tracestate`` if present) header
    when an OpenTelemetry span is active, so downstream services can correlate
    traces. No-op when OTel is not installed or no span is active.
    """
    ip_url, hostname, original_url = _resolve_safe_url(url)
    merged_headers = dict(headers or {})
    # Preserve any caller-supplied Host header only if it matches the hostname;
    # otherwise force it to the validated hostname for cert + vhost routing.
    merged_headers["Host"] = hostname

    # Inject W3C trace context. We do this AFTER all other headers are set so
    # the propagator overwrites any stale traceparent the caller might have
    # passed in. selva_observability gracefully no-ops when OTel is missing.
    try:
        from selva_observability import inject_trace_context

        inject_trace_context(merged_headers)
    except ImportError:
        # selva_observability not installed (e.g. minimal tools-only env).
        pass

    request_kwargs: dict[str, Any] = {
        "method": method,
        "url": ip_url,
        "headers": merged_headers,
        # httpx accepts an SNI override via extensions; required because the URL
        # netloc is now an IP literal which would otherwise break SNI.
        "extensions": {"sni_hostname": hostname},
    }
    if extra:
        request_kwargs.update(extra)
    return request_kwargs, original_url


class HTTPRequestTool(BaseTool):
    name = "http_request"
    description = (
        "Make an HTTP request to an external URL. "
        "Supports GET, POST, PUT, DELETE methods. "
        "SSRF protection blocks requests to private IP ranges "
        "(connection is pinned to the validated IP to prevent DNS rebinding)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target URL",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE", "PATCH"],
                    "default": "GET",
                    "description": "HTTP method",
                },
                "headers": {
                    "type": "object",
                    "description": "Request headers as key-value pairs",
                    "default": {},
                },
                "body": {
                    "description": "Request body (string or JSON object)",
                    "default": None,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds",
                    "default": 30,
                },
            },
            "required": ["url"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import httpx

        url = kwargs.get("url", "")
        method = kwargs.get("method", "GET").upper()
        headers = kwargs.get("headers", {}) or {}
        body = kwargs.get("body")
        timeout = kwargs.get("timeout", 30)

        try:
            extra: dict[str, Any] = {}
            if body is not None:
                if isinstance(body, dict):
                    extra["json"] = body
                else:
                    extra["content"] = str(body)
            request_kwargs, original_url = _build_safe_request_kwargs(
                method, url, headers, extra=extra
            )
        except ValueError as exc:
            return ToolResult(success=False, error=f"URL validation failed: {exc}")

        try:
            # Disable retries so a transient connect failure cannot be exploited
            # to widen the (already-eliminated) rebind window via httpx-internal
            # re-resolution.
            transport = httpx.AsyncHTTPTransport(retries=0)
            async with httpx.AsyncClient(
                timeout=float(timeout),
                transport=transport,
                trust_env=False,
            ) as client:
                resp = await client.request(**request_kwargs)

            resp_body = resp.text[:50000]  # Cap response size
            resp_headers = dict(resp.headers)

            return ToolResult(
                output=f"HTTP {resp.status_code} {method} {original_url}\n{resp_body[:2000]}",
                data={
                    "status_code": resp.status_code,
                    "headers": resp_headers,
                    "body": resp_body,
                    "url": original_url,
                },
            )
        except ssl.SSLError as exc:
            logger.error("http_request TLS verification failed: %s", exc)
            return ToolResult(success=False, error=f"TLS verification failed: {exc}")
        except Exception as exc:
            logger.error("http_request failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class GraphQLQueryTool(BaseTool):
    name = "graphql_query"
    description = (
        "Execute a GraphQL query against a remote endpoint. "
        "SSRF protection blocks requests to private IP ranges "
        "(connection is pinned to the validated IP to prevent DNS rebinding)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "GraphQL endpoint URL",
                },
                "query": {
                    "type": "string",
                    "description": "GraphQL query string",
                },
                "variables": {
                    "type": "object",
                    "description": "Query variables",
                    "default": {},
                },
                "headers": {
                    "type": "object",
                    "description": "Request headers",
                    "default": {},
                },
            },
            "required": ["url", "query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import httpx

        url = kwargs.get("url", "")
        query = kwargs.get("query", "")
        variables = kwargs.get("variables", {}) or {}
        headers = kwargs.get("headers", {}) or {}

        try:
            request_kwargs, original_url = _build_safe_request_kwargs(
                "POST",
                url,
                headers,
                extra={"json": {"query": query, "variables": variables}},
            )
        except ValueError as exc:
            return ToolResult(success=False, error=f"URL validation failed: {exc}")

        try:
            transport = httpx.AsyncHTTPTransport(retries=0)
            async with httpx.AsyncClient(
                timeout=30.0,
                transport=transport,
                trust_env=False,
            ) as client:
                resp = await client.request(**request_kwargs)
                resp.raise_for_status()
                data = resp.json()

            if "errors" in data and data["errors"]:
                error_msgs = "; ".join(e.get("message", "") for e in data["errors"])
                return ToolResult(
                    output=f"GraphQL errors ({original_url}): {error_msgs}",
                    data=data,
                )

            return ToolResult(
                output=f"GraphQL query returned data from {original_url}",
                data=data,
            )
        except ssl.SSLError as exc:
            logger.error("graphql_query TLS verification failed: %s", exc)
            return ToolResult(success=False, error=f"TLS verification failed: {exc}")
        except Exception as exc:
            logger.error("graphql_query failed: %s", exc)
            return ToolResult(success=False, error=str(exc))


class WebhookSendTool(BaseTool):
    name = "webhook_send"
    description = (
        "Send a JSON payload to a webhook URL. "
        "Optionally signs the payload with HMAC-SHA256 in X-Signature header. "
        "SSRF protection blocks requests to private IP ranges "
        "(connection is pinned to the validated IP to prevent DNS rebinding)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Webhook target URL",
                },
                "payload": {
                    "type": "object",
                    "description": "JSON payload to send",
                },
                "secret": {
                    "type": "string",
                    "description": "Optional HMAC-SHA256 signing secret",
                    "default": "",
                },
            },
            "required": ["url", "payload"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        import json

        import httpx

        url = kwargs.get("url", "")
        payload = kwargs.get("payload", {})
        secret = kwargs.get("secret", "")

        headers: dict[str, str] = {"Content-Type": "application/json"}
        body_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        if secret:
            signature = hmac.new(secret.encode("utf-8"), body_bytes, hashlib.sha256).hexdigest()
            headers["X-Signature"] = f"sha256={signature}"

        try:
            request_kwargs, original_url = _build_safe_request_kwargs(
                "POST",
                url,
                headers,
                extra={"content": body_bytes},
            )
        except ValueError as exc:
            return ToolResult(success=False, error=f"URL validation failed: {exc}")

        try:
            transport = httpx.AsyncHTTPTransport(retries=0)
            async with httpx.AsyncClient(
                timeout=15.0,
                transport=transport,
                trust_env=False,
            ) as client:
                resp = await client.request(**request_kwargs)

            return ToolResult(
                output=f"Webhook sent to {original_url}: HTTP {resp.status_code}",
                data={
                    "status_code": resp.status_code,
                    "url": original_url,
                    "signed": bool(secret),
                },
            )
        except ssl.SSLError as exc:
            logger.error("webhook_send TLS verification failed: %s", exc)
            return ToolResult(success=False, error=f"TLS verification failed: {exc}")
        except Exception as exc:
            logger.error("webhook_send failed: %s", exc)
            return ToolResult(success=False, error=str(exc))
