"""Provider webhook management tools (RFC 0008 Sprint 1).

Implements the ``webhooks.*`` tool family described in
``internal-devops/rfcs/0008-selva-provider-webhook-management.md``:

- ``webhooks.stripe.create`` — POST /v1/webhook_endpoints, capture
  ``whsec_...`` from the response, hand it immediately to RFC 0005's
  ``secrets.write_kubernetes_secret``. Return the Stripe webhook ID
  only. The signing secret never appears in the return value, the
  tool's logs, or the audit row.
- ``webhooks.stripe.list`` — GET /v1/webhook_endpoints. Returns webhook
  IDs + URLs only; no secrets.
- ``webhooks.stripe.delete`` — DELETE /v1/webhook_endpoints/{id}.
  Idempotent on 404.
- ``webhooks.resend.create`` — POST /webhooks. Captures signing secret
  from response, same pattern.
- ``webhooks.janua.register_oidc_redirect`` — PATCH /admin/clients/{id}
  on the Janua admin API. No signing secret, but still HITL-gated
  because a rogue redirect URI is the classic OAuth account-takeover
  vector.

The critical invariant (RFC 0008 §"The critical invariant"):

    The webhook signing secret is captured by the tool at API response
    time and written DIRECTLY to the K8s secret via RFC 0005's
    secrets.write_kubernetes_secret. It never passes through a human,
    never lands in chat history, never gets logged.

Every source reference to the provider's signing secret lives in a
single short block in each ``*_create`` helper, and the tool's own
test suite greps the source to ensure no new references leak.

HITL gates per RFC 0008:

| op       | dev   | staging | prod      |
| -------- | ----- | ------- | --------- |
| create   | ALLOW | ASK     | ASK_DUAL  |
| list     | ALLOW | ALLOW   | ALLOW     |
| delete   | ALLOW | ASK     | ASK_DUAL  |
| redirect | ALLOW | ASK     | ASK_DUAL  |

Provider authentication: API keys are read from environment variables
populated by ``envFrom`` in the worker Deployment (standard pattern,
same as the email tools reading RESEND_API_KEY). Per RFC 0008, full-
access API keys are assumed for Sprint 1 — Stripe Connect / restricted
key handling lands in a later sprint.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from enum import StrEnum
from typing import Any

import httpx

from ..audience import Audience
from ..base import BaseTool, ToolResult
from .k8s_secret import (
    ALLOWED_CLUSTERS,
    ALLOWED_NAMESPACES,
    KubernetesSecretWriteTool,
    SecretSource,
)

logger = logging.getLogger("selva.tools.webhooks")

# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------

STRIPE_API_BASE = "https://api.stripe.com/v1"
RESEND_API_BASE = "https://api.resend.com"
# Janua admin API base defaults to the prod URL; override via env for
# staging/dev.
JANUA_ADMIN_API_BASE_ENV = "JANUA_ADMIN_API_BASE"
JANUA_ADMIN_API_BASE_DEFAULT = "https://api.janua.madfam.io"

HTTP_TIMEOUT_SECONDS = 15.0

# Default Stripe event types requested on create when the caller
# doesn't specify any. The RFC leaves the per-provider defaults to
# judgment; for the Dhanam billing surface these cover the checkout
# → invoicing loop. New defaults should be added here, not at callers.
STRIPE_DEFAULT_EVENTS = (
    "payment_intent.succeeded",
    "payment_intent.payment_failed",
    "charge.succeeded",
    "charge.failed",
    "invoice.paid",
    "invoice.payment_failed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "checkout.session.completed",
)


class Provider(StrEnum):
    STRIPE = "stripe"
    RESEND = "resend"
    JANUA = "janua"


class _WebhookProviderError(Exception):
    """Raised when a provider API call fails in a user-facing way.

    The message is scrubbed (status code + generic error class only) so
    nothing the provider returned — which might include a leaked secret
    or API-key echo — flows back through the tool's error path.
    """


# ---------------------------------------------------------------------------
# Helpers (pure)
# ---------------------------------------------------------------------------


def _sha256_prefix(value: str) -> str:
    """First 8 hex chars of SHA-256(value). Used for URL redaction."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:8]


def _resolve_env() -> str:
    """Map the ``SELVA_ENV`` env var to an HITL bucket.

    Unknown values (including missing) fall back to ``staging`` —
    fail-closed: unknown env should not get the dev ALLOW path.
    """
    raw = os.environ.get("SELVA_ENV", "").lower()
    if raw in ("dev", "development", "local"):
        return "dev"
    if raw in ("prod", "production"):
        return "prod"
    return "staging"


def _resolve_hitl_level(env: str, *, dual_for_prod: bool = True) -> str:
    """Return the HITL level string for the action + env.

    ``dual_for_prod`` controls whether prod escalates to ``ask_dual``
    (True, matching RFC 0008 for create/delete/redirect) or stays at
    ``ask`` (not currently used; kept for Sprint 2 rotation variants).
    """
    try:
        from selva_permissions.engine import PermissionEngine
        from selva_permissions.types import (
            ActionCategory,
            PermissionLevel,
        )
    except Exception:  # pragma: no cover
        return "ask"

    prod_level = PermissionLevel.ASK_DUAL if dual_for_prod else PermissionLevel.ASK
    env_overrides = {
        "dev": PermissionLevel.ALLOW,
        "staging": PermissionLevel.ASK,
        "prod": prod_level,
    }
    engine = PermissionEngine(overrides={ActionCategory.WEBHOOK_MANAGEMENT: env_overrides[env]})
    result = engine.evaluate(ActionCategory.WEBHOOK_MANAGEMENT)
    return result.level.value


def _read_api_key(env_var: str) -> str | None:
    """Read a provider API key from env. Never logs the value."""
    raw = os.environ.get(env_var)
    if not raw:
        return None
    return raw


# ---------------------------------------------------------------------------
# Audit bridge (lazy-import, fail-soft)
# ---------------------------------------------------------------------------


def _audit_webhook(
    *,
    approval_request_id: str,
    agent_id: str | None,
    actor_user_sub: str | None,
    provider: str,
    action: str,
    webhook_id: str | None,
    target_url_sha256_prefix: str | None,
    events_registered: list[str] | None,
    linked_secret_audit_id: str | None,
    resulting_secret_name: str | None,
    rationale: str,
    status: str,
    error_message: str | None,
    request_id: str | None = None,
) -> str | None:
    """Append a row to ``webhook_audit_log`` via nexus-api. Never raises."""
    try:
        from nexus_api.audit.webhook_audit import append_audit_row
    except Exception:  # pragma: no cover — missing dep is dev-only
        logger.debug("nexus_api webhook_audit module unavailable; skipping DB write")
        return None
    try:
        return append_audit_row(
            approval_request_id=approval_request_id,
            agent_id=agent_id,
            actor_user_sub=actor_user_sub,
            provider=provider,
            action=action,
            webhook_id=webhook_id,
            target_url_sha256_prefix=target_url_sha256_prefix,
            events_registered=events_registered,
            linked_secret_audit_id=linked_secret_audit_id,
            resulting_secret_name=resulting_secret_name,
            rationale=rationale,
            status=status,
            error_message=error_message,
            request_id=request_id,
        )
    except Exception:  # noqa: BLE001 — audit MUST NOT leak or block
        logger.error("webhook audit append failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Provider API wrappers
# ---------------------------------------------------------------------------


def _stripe_create_webhook_endpoint(
    *,
    api_key: str,
    url: str,
    events: list[str],
    description: str | None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """POST /v1/webhook_endpoints. Returns the parsed JSON response.

    CAUTION: the response contains ``secret`` (``whsec_...``). Callers
    MUST immediately pass the secret to the k8s secret writer and
    discard the return value. No other reference to the returned dict
    should survive beyond that call site.

    Stripe accepts application/x-www-form-urlencoded with array-bracket
    repetition for list fields (``enabled_events[]=...&enabled_events[]=...``).
    We build the body manually to preserve that array shape — httpx's
    ``data=`` dict-form would collapse duplicates.
    """
    import urllib.parse as _urlparse

    pairs: list[tuple[str, str]] = [("url", url)]
    for e in events:
        pairs.append(("enabled_events[]", e))
    if description:
        pairs.append(("description", description))
    body = _urlparse.urlencode(pairs)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    owned = client is None
    if owned:
        client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    try:
        resp = client.post(
            f"{STRIPE_API_BASE}/webhook_endpoints",
            content=body,
            headers=headers,
        )
    finally:
        if owned and client is not None:
            client.close()
    if resp.status_code >= 400:
        raise _WebhookProviderError(f"stripe create returned status={resp.status_code}")
    return resp.json()


def _stripe_list_webhook_endpoints(
    *, api_key: str, client: httpx.Client | None = None
) -> list[dict[str, Any]]:
    """GET /v1/webhook_endpoints. Returns the ``data`` array.

    Stripe does NOT return the signing secret on list endpoints (the
    secret is only returned once, on create). So the values here are
    safe to surface.
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    owned = client is None
    if owned:
        client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    try:
        resp = client.get(
            f"{STRIPE_API_BASE}/webhook_endpoints",
            headers=headers,
            params={"limit": 100},
        )
    finally:
        if owned and client is not None:
            client.close()
    if resp.status_code >= 400:
        raise _WebhookProviderError(f"stripe list returned status={resp.status_code}")
    body = resp.json()
    return list(body.get("data") or [])


def _stripe_delete_webhook_endpoint(
    *, api_key: str, webhook_id: str, client: httpx.Client | None = None
) -> bool:
    """DELETE /v1/webhook_endpoints/{id}. Returns True if deleted,
    False if already absent (404). Raises on other errors."""
    headers = {"Authorization": f"Bearer {api_key}"}
    owned = client is None
    if owned:
        client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    try:
        resp = client.delete(
            f"{STRIPE_API_BASE}/webhook_endpoints/{webhook_id}",
            headers=headers,
        )
    finally:
        if owned and client is not None:
            client.close()
    if resp.status_code == 404:
        return False
    if resp.status_code >= 400:
        raise _WebhookProviderError(f"stripe delete returned status={resp.status_code}")
    return True


def _resend_create_webhook(
    *,
    api_key: str,
    url: str,
    events: list[str] | None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """POST /webhooks on Resend. Returns parsed JSON.

    Same caution as Stripe: response contains ``signing_secret``.
    Caller MUST hand it to the k8s writer immediately.
    """
    body: dict[str, Any] = {"endpoint_url": url}
    if events:
        body["events"] = events
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    owned = client is None
    if owned:
        client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    try:
        resp = client.post(
            f"{RESEND_API_BASE}/webhooks",
            json=body,
            headers=headers,
        )
    finally:
        if owned and client is not None:
            client.close()
    if resp.status_code >= 400:
        raise _WebhookProviderError(f"resend create returned status={resp.status_code}")
    return resp.json()


def _janua_register_redirect(
    *,
    admin_token: str,
    client_id: str,
    redirect_uri: str,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """PATCH /admin/clients/{id} to add ``redirect_uri`` to the allow list."""
    base = os.environ.get(JANUA_ADMIN_API_BASE_ENV, JANUA_ADMIN_API_BASE_DEFAULT)
    headers = {
        "Authorization": f"Bearer {admin_token}",
        "Content-Type": "application/json",
    }
    body = {"add_redirect_uri": redirect_uri}
    owned = client is None
    if owned:
        client = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
    try:
        resp = client.patch(
            f"{base}/admin/clients/{client_id}",
            json=body,
            headers=headers,
        )
    finally:
        if owned and client is not None:
            client.close()
    if resp.status_code >= 400:
        raise _WebhookProviderError(f"janua redirect register returned status={resp.status_code}")
    return resp.json()


# ---------------------------------------------------------------------------
# Shared argument validation
# ---------------------------------------------------------------------------


def _validate_common_webhook_args(
    *,
    url: str | None,
    rationale: str,
) -> str | None:
    """Return an error string if common arg validation fails, else None."""
    if not url or not isinstance(url, str):
        return "url is required"
    if len(url) > 2048:
        return "url exceeds 2048 chars"
    if not url.startswith(("http://", "https://")):
        return "url must be http(s)"
    if not rationale or len(rationale) < 10:
        return "rationale is required (>= 10 chars, human-readable why)"
    return None


def _validate_destination_args(
    *,
    destination_cluster: str,
    destination_namespace: str,
    destination_secret_name: str,
    destination_secret_key: str,
) -> str | None:
    """Return an error string if the K8s destination args are invalid."""
    if destination_cluster not in ALLOWED_CLUSTERS:
        return f"destination_cluster must be one of {sorted(ALLOWED_CLUSTERS)}"
    if destination_namespace not in ALLOWED_NAMESPACES:
        return f"destination_namespace {destination_namespace!r} is not in the allow-list"
    if not destination_secret_name or not destination_secret_key:
        return "destination_secret_name and destination_secret_key are required"
    return None


# ---------------------------------------------------------------------------
# Tool: webhooks.stripe.create
# ---------------------------------------------------------------------------


class StripeWebhookCreateTool(BaseTool):
    """``webhooks.stripe.create`` — RFC 0008 Sprint 1.

    Registers a new Stripe webhook endpoint and captures the returned
    signing secret directly into a K8s Secret via RFC 0005's
    ``secrets.write_kubernetes_secret``. The signing secret is NEVER
    returned to the caller, NEVER logged, and NEVER written to the
    webhook audit row.
    """

    name = "webhooks_stripe_create"
    description = (
        "Create a Stripe webhook endpoint. Captures the provider-returned "
        "signing secret and writes it to the specified K8s Secret via the "
        "RFC 0005 secret writer in a single atomic flow. The signing "
        "secret is never returned, logged, or persisted outside the K8s "
        "Secret. Gated by WEBHOOK_MANAGEMENT (dev=ALLOW, staging=ASK, "
        "prod=ASK_DUAL)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": (
                        "Stripe account nickname (e.g. 'stripe-mx'). Used "
                        "only for operator-visible logging; the actual API "
                        "key is read from ``api_key_env``."
                    ),
                },
                "url": {
                    "type": "string",
                    "description": "HTTPS endpoint to receive webhook events.",
                },
                "events": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Stripe event types to subscribe to. Defaults to "
                        "the RFC 0008 ecosystem-billing set when empty."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Human-readable description on Stripe's side.",
                },
                "api_key_env": {
                    "type": "string",
                    "description": (
                        "Env var holding the Stripe secret key (e.g. 'STRIPE_MX_SECRET_KEY')."
                    ),
                },
                "destination_cluster": {
                    "type": "string",
                    "enum": sorted(ALLOWED_CLUSTERS),
                },
                "destination_namespace": {"type": "string"},
                "destination_secret_name": {"type": "string"},
                "destination_secret_key": {"type": "string"},
                "rationale": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": [
                "url",
                "api_key_env",
                "destination_cluster",
                "destination_namespace",
                "destination_secret_name",
                "destination_secret_key",
                "rationale",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        api_key_env = str(kwargs.get("api_key_env") or "")
        destination_cluster = str(kwargs.get("destination_cluster") or "")
        destination_namespace = str(kwargs.get("destination_namespace") or "")
        destination_secret_name = str(kwargs.get("destination_secret_name") or "")
        destination_secret_key = str(kwargs.get("destination_secret_key") or "")
        account_id = str(kwargs.get("account_id") or "")
        rationale = str(kwargs.get("rationale") or "")
        events_in = kwargs.get("events") or []
        description = kwargs.get("description") or None
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")
        http_client: httpx.Client | None = kwargs.get("_http_client")
        secret_writer: KubernetesSecretWriteTool | None = kwargs.get("_secret_writer")

        common_err = _validate_common_webhook_args(
            url=url if isinstance(url, str) else None, rationale=rationale
        )
        if common_err:
            return ToolResult(success=False, error=common_err)
        dest_err = _validate_destination_args(
            destination_cluster=destination_cluster,
            destination_namespace=destination_namespace,
            destination_secret_name=destination_secret_name,
            destination_secret_key=destination_secret_key,
        )
        if dest_err:
            return ToolResult(success=False, error=dest_err)
        if not api_key_env:
            return ToolResult(success=False, error="api_key_env is required")

        assert isinstance(url, str)  # narrowed by _validate_common_webhook_args
        url_prefix = _sha256_prefix(url)
        events_final = list(events_in) if events_in else list(STRIPE_DEFAULT_EVENTS)
        env = _resolve_env()
        hitl_level = _resolve_hitl_level(env, dual_for_prod=True)
        approval_request_id = str(uuid.uuid4())

        logger.info(
            "stripe webhook create requested account=%s url_prefix=%s "
            "events=%d dest=%s/%s:%s hitl=%s approval_id=%s",
            account_id or "unknown",
            url_prefix,
            len(events_final),
            destination_namespace,
            destination_secret_name,
            destination_secret_key,
            hitl_level,
            approval_request_id,
        )

        if hitl_level in ("ask", "ask_dual"):
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.STRIPE.value,
                action="create",
                webhook_id=None,
                target_url_sha256_prefix=url_prefix,
                events_registered=events_final,
                linked_secret_audit_id=None,
                resulting_secret_name=(
                    f"{destination_namespace}/{destination_secret_name}:{destination_secret_key}"
                ),
                rationale=rationale,
                status="pending_approval",
                error_message=None,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(
                output=(
                    f"Stripe webhook create for url_prefix={url_prefix} is "
                    f"pending {hitl_level} approval."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "provider": Provider.STRIPE.value,
                    "target_url_sha256_prefix": url_prefix,
                },
            )

        api_key = _read_api_key(api_key_env)
        if not api_key:
            err = f"provider API key env var {api_key_env!r} not set"
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.STRIPE.value,
                action="create",
                webhook_id=None,
                target_url_sha256_prefix=url_prefix,
                events_registered=events_final,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=err,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=err)

        webhook_id: str | None = None
        try:
            response = _stripe_create_webhook_endpoint(
                api_key=api_key,
                url=url,
                events=events_final,
                description=description,
                client=http_client,
            )
            webhook_id = str(response.get("id") or "")
            # ---- CAPTURE-AND-FORWARD --------------------------------
            # The next two lines are the ONLY place in this module
            # where a signing secret exists as a Python string. It
            # flows directly into the k8s secret writer and is then
            # shadowed by ``None``. Do not add references.
            signing_secret = response.get("secret")
            if not isinstance(signing_secret, str) or not signing_secret:
                raise _WebhookProviderError(
                    "stripe create response did not include a signing secret"
                )
            writer = secret_writer or KubernetesSecretWriteTool()
            write_result = await writer.execute(
                cluster=destination_cluster,
                namespace=destination_namespace,
                secret_name=destination_secret_name,
                key=destination_secret_key,
                value=signing_secret,
                source=SecretSource.STRIPE_API.value,
                rationale=(f"RFC 0008 webhook create for {account_id or 'stripe'}: {rationale}"),
                agent_id=agent_id,
                actor_user_sub=actor_user_sub,
            )
            # Scrub local references to the secret as soon as the
            # handoff returns. ``signing_secret`` is re-bound to None;
            # ``response`` is cleared so a later reference to
            # ``response["secret"]`` is impossible.
            signing_secret = None  # noqa: F841 — deliberate shadowing
            response.pop("secret", None)
        except _WebhookProviderError as exc:
            msg = str(exc)
            logger.error(
                "stripe webhook create failed url_prefix=%s err=%s",
                url_prefix,
                msg,
            )
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.STRIPE.value,
                action="create",
                webhook_id=webhook_id,
                target_url_sha256_prefix=url_prefix,
                events_registered=events_final,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=f"provider api error: {msg}")
        except Exception as exc:  # noqa: BLE001 — scrub before surfacing
            err_class = type(exc).__name__
            logger.error(
                "stripe webhook create unexpected failure url_prefix=%s err_class=%s",
                url_prefix,
                err_class,
            )
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.STRIPE.value,
                action="create",
                webhook_id=webhook_id,
                target_url_sha256_prefix=url_prefix,
                events_registered=events_final,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=err_class,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(
                success=False,
                error=f"webhook create failure ({err_class}); see audit row",
            )

        secret_status = write_result.data.get("status") if write_result.data else None
        secret_approval_id = (
            write_result.data.get("approval_request_id") if write_result.data else None
        )
        resulting_secret_name = (
            f"{destination_namespace}/{destination_secret_name}:{destination_secret_key}"
        )
        _audit_webhook(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            provider=Provider.STRIPE.value,
            action="create",
            webhook_id=webhook_id,
            target_url_sha256_prefix=url_prefix,
            events_registered=events_final,
            linked_secret_audit_id=secret_approval_id,
            resulting_secret_name=resulting_secret_name,
            rationale=rationale,
            status="applied" if write_result.success else "failed",
            error_message=(
                None if write_result.success else (write_result.error or "secret write failed")
            ),
            request_id=str(request_id) if request_id else None,
        )

        return ToolResult(
            success=write_result.success,
            output=(
                f"Stripe webhook {webhook_id} created; signing secret "
                f"handed off to {resulting_secret_name} ({secret_status})."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied" if write_result.success else "failed",
                "hitl_level": hitl_level,
                "provider": Provider.STRIPE.value,
                "webhook_id": webhook_id,
                "target_url_sha256_prefix": url_prefix,
                "events_registered": events_final,
                "resulting_secret_name": resulting_secret_name,
                "linked_secret_status": secret_status,
            },
        )


# ---------------------------------------------------------------------------
# Tool: webhooks.stripe.list
# ---------------------------------------------------------------------------


class StripeWebhookListTool(BaseTool):
    """``webhooks.stripe.list`` — RFC 0008 Sprint 1.

    Read-only. Returns the webhook endpoints registered with Stripe,
    without any signing secrets (Stripe returns those only on create).
    HITL: ALLOW everywhere.
    """

    name = "webhooks_stripe_list"
    description = (
        "List Stripe webhook endpoints. Returns IDs, URLs, enabled event "
        "lists, and status. Never returns signing secrets (Stripe API does "
        "not expose them on list). HITL: ALLOW in all environments."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "api_key_env": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["api_key_env"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        api_key_env = str(kwargs.get("api_key_env") or "")
        account_id = str(kwargs.get("account_id") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")
        http_client: httpx.Client | None = kwargs.get("_http_client")

        if not api_key_env:
            return ToolResult(success=False, error="api_key_env is required")
        api_key = _read_api_key(api_key_env)
        if not api_key:
            return ToolResult(
                success=False,
                error=f"provider API key env var {api_key_env!r} not set",
            )

        approval_request_id = str(uuid.uuid4())
        try:
            endpoints = _stripe_list_webhook_endpoints(api_key=api_key, client=http_client)
        except _WebhookProviderError as exc:
            msg = str(exc)
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.STRIPE.value,
                action="list",
                webhook_id=None,
                target_url_sha256_prefix=None,
                events_registered=None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=f"list (account={account_id or 'unknown'})",
                status="failed",
                error_message=msg,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=f"provider api error: {msg}")

        # Sanitised summary: id, url, events, status. NO ``secret`` key
        # even though Stripe wouldn't return one anyway — belt-and-braces.
        summaries = []
        for ep in endpoints:
            summaries.append(
                {
                    "id": ep.get("id"),
                    "url": ep.get("url"),
                    "enabled_events": ep.get("enabled_events") or [],
                    "status": ep.get("status"),
                    "created": ep.get("created"),
                }
            )

        _audit_webhook(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            provider=Provider.STRIPE.value,
            action="list",
            webhook_id=None,
            target_url_sha256_prefix=None,
            events_registered=None,
            linked_secret_audit_id=None,
            resulting_secret_name=None,
            rationale=f"list (account={account_id or 'unknown'})",
            status="applied",
            error_message=None,
            request_id=str(request_id) if request_id else None,
        )

        return ToolResult(
            output=f"Found {len(summaries)} Stripe webhook endpoint(s).",
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": "allow",
                "provider": Provider.STRIPE.value,
                "count": len(summaries),
                "endpoints": summaries,
            },
        )


# ---------------------------------------------------------------------------
# Tool: webhooks.stripe.delete
# ---------------------------------------------------------------------------


class StripeWebhookDeleteTool(BaseTool):
    """``webhooks.stripe.delete`` — RFC 0008 Sprint 1.

    Idempotent. 404 from provider is treated as success (webhook
    already gone). HITL: ASK in staging, ASK_DUAL in prod.
    """

    name = "webhooks_stripe_delete"
    description = (
        "Delete a Stripe webhook endpoint. Idempotent on 404. Gated by "
        "WEBHOOK_MANAGEMENT (dev=ALLOW, staging=ASK, prod=ASK_DUAL)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "webhook_id": {"type": "string"},
                "api_key_env": {"type": "string"},
                "rationale": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["webhook_id", "api_key_env", "rationale"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        webhook_id = str(kwargs.get("webhook_id") or "")
        api_key_env = str(kwargs.get("api_key_env") or "")
        account_id = str(kwargs.get("account_id") or "")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")
        http_client: httpx.Client | None = kwargs.get("_http_client")

        if not webhook_id:
            return ToolResult(success=False, error="webhook_id is required")
        if not api_key_env:
            return ToolResult(success=False, error="api_key_env is required")
        if not rationale or len(rationale) < 10:
            return ToolResult(
                success=False,
                error="rationale is required (>= 10 chars, human-readable why)",
            )

        env = _resolve_env()
        hitl_level = _resolve_hitl_level(env, dual_for_prod=True)
        approval_request_id = str(uuid.uuid4())

        if hitl_level in ("ask", "ask_dual"):
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.STRIPE.value,
                action="delete",
                webhook_id=webhook_id,
                target_url_sha256_prefix=None,
                events_registered=None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="pending_approval",
                error_message=None,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(
                output=(
                    f"Stripe webhook delete for {webhook_id} is pending {hitl_level} approval."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "provider": Provider.STRIPE.value,
                    "webhook_id": webhook_id,
                },
            )

        api_key = _read_api_key(api_key_env)
        if not api_key:
            return ToolResult(
                success=False,
                error=f"provider API key env var {api_key_env!r} not set",
            )

        try:
            deleted = _stripe_delete_webhook_endpoint(
                api_key=api_key, webhook_id=webhook_id, client=http_client
            )
        except _WebhookProviderError as exc:
            msg = str(exc)
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.STRIPE.value,
                action="delete",
                webhook_id=webhook_id,
                target_url_sha256_prefix=None,
                events_registered=None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=f"provider api error: {msg}")

        idempotent = not deleted  # True when 404 — webhook was already gone.
        _audit_webhook(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            provider=Provider.STRIPE.value,
            action="delete",
            webhook_id=webhook_id,
            target_url_sha256_prefix=None,
            events_registered=None,
            linked_secret_audit_id=None,
            resulting_secret_name=None,
            rationale=rationale,
            status="applied",
            error_message=None,
            request_id=str(request_id) if request_id else None,
        )
        return ToolResult(
            output=(
                f"Stripe webhook {webhook_id} {'already absent' if idempotent else 'deleted'}."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": hitl_level,
                "provider": Provider.STRIPE.value,
                "webhook_id": webhook_id,
                "idempotent": idempotent,
                "account_id": account_id,
            },
        )


# ---------------------------------------------------------------------------
# Tool: webhooks.resend.create
# ---------------------------------------------------------------------------


class ResendWebhookCreateTool(BaseTool):
    """``webhooks.resend.create`` — RFC 0008 Sprint 1.

    Same capture-and-forward pattern as Stripe create. Resend returns
    the signing secret as ``signing_secret`` in the response body.
    """

    name = "webhooks_resend_create"
    description = (
        "Create a Resend webhook endpoint. Captures the provider-returned "
        "signing secret and writes it to the specified K8s Secret via the "
        "RFC 0005 secret writer. The signing secret is never returned, "
        "logged, or persisted outside the K8s Secret. Gated by "
        "WEBHOOK_MANAGEMENT (dev=ALLOW, staging=ASK, prod=ASK_DUAL)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "events": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Resend event types (optional).",
                },
                "api_key_env": {
                    "type": "string",
                    "description": ("Env var holding the Resend API key (e.g. 'RESEND_API_KEY')."),
                },
                "destination_cluster": {
                    "type": "string",
                    "enum": sorted(ALLOWED_CLUSTERS),
                },
                "destination_namespace": {"type": "string"},
                "destination_secret_name": {"type": "string"},
                "destination_secret_key": {"type": "string"},
                "rationale": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": [
                "url",
                "api_key_env",
                "destination_cluster",
                "destination_namespace",
                "destination_secret_name",
                "destination_secret_key",
                "rationale",
            ],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url")
        api_key_env = str(kwargs.get("api_key_env") or "")
        destination_cluster = str(kwargs.get("destination_cluster") or "")
        destination_namespace = str(kwargs.get("destination_namespace") or "")
        destination_secret_name = str(kwargs.get("destination_secret_name") or "")
        destination_secret_key = str(kwargs.get("destination_secret_key") or "")
        rationale = str(kwargs.get("rationale") or "")
        events_in = kwargs.get("events")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")
        http_client: httpx.Client | None = kwargs.get("_http_client")
        secret_writer: KubernetesSecretWriteTool | None = kwargs.get("_secret_writer")

        common_err = _validate_common_webhook_args(
            url=url if isinstance(url, str) else None, rationale=rationale
        )
        if common_err:
            return ToolResult(success=False, error=common_err)
        dest_err = _validate_destination_args(
            destination_cluster=destination_cluster,
            destination_namespace=destination_namespace,
            destination_secret_name=destination_secret_name,
            destination_secret_key=destination_secret_key,
        )
        if dest_err:
            return ToolResult(success=False, error=dest_err)
        if not api_key_env:
            return ToolResult(success=False, error="api_key_env is required")

        assert isinstance(url, str)
        url_prefix = _sha256_prefix(url)
        env = _resolve_env()
        hitl_level = _resolve_hitl_level(env, dual_for_prod=True)
        approval_request_id = str(uuid.uuid4())

        logger.info(
            "resend webhook create requested url_prefix=%s dest=%s/%s:%s hitl=%s approval_id=%s",
            url_prefix,
            destination_namespace,
            destination_secret_name,
            destination_secret_key,
            hitl_level,
            approval_request_id,
        )

        if hitl_level in ("ask", "ask_dual"):
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.RESEND.value,
                action="create",
                webhook_id=None,
                target_url_sha256_prefix=url_prefix,
                events_registered=list(events_in) if events_in else None,
                linked_secret_audit_id=None,
                resulting_secret_name=(
                    f"{destination_namespace}/{destination_secret_name}:{destination_secret_key}"
                ),
                rationale=rationale,
                status="pending_approval",
                error_message=None,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(
                output=(
                    f"Resend webhook create for url_prefix={url_prefix} is "
                    f"pending {hitl_level} approval."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "provider": Provider.RESEND.value,
                    "target_url_sha256_prefix": url_prefix,
                },
            )

        api_key = _read_api_key(api_key_env)
        if not api_key:
            err = f"provider API key env var {api_key_env!r} not set"
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.RESEND.value,
                action="create",
                webhook_id=None,
                target_url_sha256_prefix=url_prefix,
                events_registered=list(events_in) if events_in else None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=err,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=err)

        webhook_id: str | None = None
        try:
            response = _resend_create_webhook(
                api_key=api_key,
                url=url,
                events=list(events_in) if events_in else None,
                client=http_client,
            )
            webhook_id = str(response.get("id") or "")
            # ---- CAPTURE-AND-FORWARD --------------------------------
            signing_secret = response.get("signing_secret") or response.get("secret")
            if not isinstance(signing_secret, str) or not signing_secret:
                raise _WebhookProviderError(
                    "resend create response did not include a signing secret"
                )
            writer = secret_writer or KubernetesSecretWriteTool()
            write_result = await writer.execute(
                cluster=destination_cluster,
                namespace=destination_namespace,
                secret_name=destination_secret_name,
                key=destination_secret_key,
                value=signing_secret,
                # No RESEND_API provenance in SecretSource enum yet;
                # MANUAL_INPUT is the closest fit until the enum extends.
                source=SecretSource.MANUAL_INPUT.value,
                rationale=f"RFC 0008 resend webhook create: {rationale}",
                agent_id=agent_id,
                actor_user_sub=actor_user_sub,
            )
            signing_secret = None  # noqa: F841 — deliberate shadowing
            response.pop("signing_secret", None)
            response.pop("secret", None)
        except _WebhookProviderError as exc:
            msg = str(exc)
            logger.error(
                "resend webhook create failed url_prefix=%s err=%s",
                url_prefix,
                msg,
            )
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.RESEND.value,
                action="create",
                webhook_id=webhook_id,
                target_url_sha256_prefix=url_prefix,
                events_registered=list(events_in) if events_in else None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=f"provider api error: {msg}")
        except Exception as exc:  # noqa: BLE001
            err_class = type(exc).__name__
            logger.error(
                "resend webhook create unexpected failure url_prefix=%s err_class=%s",
                url_prefix,
                err_class,
            )
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.RESEND.value,
                action="create",
                webhook_id=webhook_id,
                target_url_sha256_prefix=url_prefix,
                events_registered=list(events_in) if events_in else None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=err_class,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(
                success=False,
                error=f"webhook create failure ({err_class}); see audit row",
            )

        secret_status = write_result.data.get("status") if write_result.data else None
        secret_approval_id = (
            write_result.data.get("approval_request_id") if write_result.data else None
        )
        resulting_secret_name = (
            f"{destination_namespace}/{destination_secret_name}:{destination_secret_key}"
        )
        _audit_webhook(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            provider=Provider.RESEND.value,
            action="create",
            webhook_id=webhook_id,
            target_url_sha256_prefix=url_prefix,
            events_registered=list(events_in) if events_in else None,
            linked_secret_audit_id=secret_approval_id,
            resulting_secret_name=resulting_secret_name,
            rationale=rationale,
            status="applied" if write_result.success else "failed",
            error_message=(
                None if write_result.success else (write_result.error or "secret write failed")
            ),
            request_id=str(request_id) if request_id else None,
        )
        return ToolResult(
            success=write_result.success,
            output=(
                f"Resend webhook {webhook_id} created; signing secret "
                f"handed off to {resulting_secret_name} ({secret_status})."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied" if write_result.success else "failed",
                "hitl_level": hitl_level,
                "provider": Provider.RESEND.value,
                "webhook_id": webhook_id,
                "target_url_sha256_prefix": url_prefix,
                "resulting_secret_name": resulting_secret_name,
                "linked_secret_status": secret_status,
            },
        )


# ---------------------------------------------------------------------------
# Tool: webhooks.janua.register_oidc_redirect
# ---------------------------------------------------------------------------


class JanuaOidcRedirectRegisterTool(BaseTool):
    """``webhooks.janua.register_oidc_redirect`` — RFC 0008 Sprint 1.

    Registers a redirect URI on a Janua OAuth client. There is no
    signing secret to capture, but an incorrect redirect URI is the
    classic account-takeover vector — so this tool is ASK in staging
    and ASK_DUAL in prod, same as create/delete.
    """

    name = "webhooks_janua_register_oidc_redirect"
    description = (
        "Register an OIDC redirect URI on a Janua OAuth client. No "
        "signing secret is minted (it's a client-config update). Gated "
        "by WEBHOOK_MANAGEMENT (dev=ALLOW, staging=ASK, prod=ASK_DUAL) "
        "because a rogue redirect is an account-takeover vector."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "redirect_uri": {"type": "string"},
                "admin_token_env": {
                    "type": "string",
                    "description": (
                        "Env var holding the Janua admin token (e.g. 'JANUA_ADMIN_API_KEY')."
                    ),
                },
                "rationale": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["client_id", "redirect_uri", "admin_token_env", "rationale"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        client_id = str(kwargs.get("client_id") or "")
        redirect_uri = kwargs.get("redirect_uri")
        admin_token_env = str(kwargs.get("admin_token_env") or "")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")
        http_client: httpx.Client | None = kwargs.get("_http_client")

        if not client_id:
            return ToolResult(success=False, error="client_id is required")
        common_err = _validate_common_webhook_args(
            url=redirect_uri if isinstance(redirect_uri, str) else None,
            rationale=rationale,
        )
        if common_err:
            # Rename "url" → "redirect_uri" for user clarity.
            return ToolResult(
                success=False,
                error=common_err.replace("url", "redirect_uri"),
            )
        if not admin_token_env:
            return ToolResult(success=False, error="admin_token_env is required")

        assert isinstance(redirect_uri, str)
        uri_prefix = _sha256_prefix(redirect_uri)
        env = _resolve_env()
        hitl_level = _resolve_hitl_level(env, dual_for_prod=True)
        approval_request_id = str(uuid.uuid4())

        logger.info(
            "janua redirect register requested client=%s uri_prefix=%s hitl=%s approval_id=%s",
            client_id,
            uri_prefix,
            hitl_level,
            approval_request_id,
        )

        if hitl_level in ("ask", "ask_dual"):
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.JANUA.value,
                action="register_oidc_redirect",
                webhook_id=client_id,
                target_url_sha256_prefix=uri_prefix,
                events_registered=None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="pending_approval",
                error_message=None,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(
                output=(
                    f"Janua redirect register for client={client_id} "
                    f"uri_prefix={uri_prefix} is pending {hitl_level} approval."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "provider": Provider.JANUA.value,
                    "client_id": client_id,
                    "target_url_sha256_prefix": uri_prefix,
                },
            )

        admin_token = _read_api_key(admin_token_env)
        if not admin_token:
            err = f"admin token env var {admin_token_env!r} not set"
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.JANUA.value,
                action="register_oidc_redirect",
                webhook_id=client_id,
                target_url_sha256_prefix=uri_prefix,
                events_registered=None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=err,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=err)

        try:
            _ = _janua_register_redirect(
                admin_token=admin_token,
                client_id=client_id,
                redirect_uri=redirect_uri,
                client=http_client,
            )
        except _WebhookProviderError as exc:
            msg = str(exc)
            _audit_webhook(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                provider=Provider.JANUA.value,
                action="register_oidc_redirect",
                webhook_id=client_id,
                target_url_sha256_prefix=uri_prefix,
                events_registered=None,
                linked_secret_audit_id=None,
                resulting_secret_name=None,
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=str(request_id) if request_id else None,
            )
            return ToolResult(success=False, error=f"provider api error: {msg}")

        _audit_webhook(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            provider=Provider.JANUA.value,
            action="register_oidc_redirect",
            webhook_id=client_id,
            target_url_sha256_prefix=uri_prefix,
            events_registered=None,
            linked_secret_audit_id=None,
            resulting_secret_name=None,
            rationale=rationale,
            status="applied",
            error_message=None,
            request_id=str(request_id) if request_id else None,
        )
        return ToolResult(
            output=(
                f"Janua OIDC redirect registered on client={client_id} (uri_prefix={uri_prefix})."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": hitl_level,
                "provider": Provider.JANUA.value,
                "client_id": client_id,
                "target_url_sha256_prefix": uri_prefix,
            },
        )


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    StripeWebhookCreateTool,
    StripeWebhookListTool,
    StripeWebhookDeleteTool,
    ResendWebhookCreateTool,
    JanuaOidcRedirectRegisterTool,
):
    _cls.audience = Audience.PLATFORM
