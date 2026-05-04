from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import socket
import urllib.parse
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, status

from ..config import get_settings
from ..memory_store.db import memory_store
from ..tasks.acp_tasks import run_acp_workflow_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gateway", tags=["Gateway"])

# ---------------------------------------------------------------------------
# Private IP ranges that must be blocked to prevent SSRF
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


def _validate_webhook_url(url: str) -> str:
    """Validate a user-supplied URL to prevent SSRF attacks.

    Checks:
    - Length <= 2048 characters
    - Scheme must be http or https
    - Hostname must resolve to a non-private IP address

    Returns the cleaned URL on success, or raises HTTPException(400) with a
    descriptive reason on failure.

    NOTE: This validator only resolves the hostname *once* at admission time.
    The actual HTTP fetch happens later inside ``run_acp_workflow_task`` (a
    Celery task), which re-resolves the hostname. A malicious DNS server can
    therefore return a public IP at admission and a private IP at fetch time
    (DNS rebinding). Mitigations belong in the Celery task itself --
    pin-to-IP-with-SNI-override (see ``http_tools._resolve_safe_url``) is the
    full fix. Tracked separately; do not rely on this function alone for
    end-to-end SSRF protection of dispatched URLs.
    """
    if len(url) > 2048:
        raise HTTPException(
            status_code=400,
            detail="Invalid URL: exceeds maximum length of 2048 characters",
        )

    parsed = urllib.parse.urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="Invalid URL: scheme must be http or https")

    hostname = parsed.hostname
    if not hostname:
        raise HTTPException(status_code=400, detail="Invalid URL: missing hostname")

    try:
        addrinfos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise HTTPException(
            status_code=400, detail="Invalid URL: hostname could not be resolved"
        ) from exc

    for _family, _type, _proto, _canonname, sockaddr in addrinfos:
        ip = ipaddress.ip_address(sockaddr[0])
        for network in _BLOCKED_NETWORKS:
            if ip in network:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid URL: hostname resolves to a private/reserved IP address",
                )

    return url


def _require_secret(env_name: str, value: str | None) -> None:
    """Refuse the request with 503 when a webhook secret is unconfigured.

    Use at the top of every handler that authenticates inbound webhooks.
    Matches the Discord/WhatsApp/generic pattern hardened in v2.2.x: an
    unset secret is a misconfiguration, not a license to accept arbitrary
    unauthenticated POSTs.
    """
    if not value:
        logger.error(
            "%s webhook received but %s is unset; refusing to verify",
            env_name.removesuffix("_SECRET").removesuffix("_TOKEN").lower(),
            env_name,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook endpoint not configured",
        )


def _verify_hmac(body: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verification for incoming webhook payloads.

    SECURITY: Refuses verification when the secret is empty. An unconfigured
    secret env var is a misconfiguration, not a license to accept arbitrary
    unauthenticated POSTs from the public internet. Operators MUST set the
    corresponding webhook secret env var (see RUNBOOK / handler docstrings).
    """
    if not secret:
        logger.error(
            "HMAC verification attempted with empty secret -- rejecting. "
            "Set the corresponding webhook secret env var to enable this endpoint."
        )
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


@router.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None),
) -> dict[str, Any]:
    """
    Hermes-style multi-channel gateway — Telegram.

    Validates the ``X-Telegram-Bot-Api-Secret-Token`` header (set when
    registering the webhook via ``setWebhook?secret_token=...``) and routes
    the ``/initiate_acp <url>`` slash command to a Celery ACP task.
    """
    settings = get_settings()
    _require_secret("TELEGRAM_WEBHOOK_SECRET", settings.telegram_webhook_secret)
    body = await request.body()

    if not x_telegram_bot_api_secret_token:
        raise HTTPException(status_code=401, detail="Missing Telegram secret token header")
    if not hmac.compare_digest(
        settings.telegram_webhook_secret,
        x_telegram_bot_api_secret_token,
    ):
        raise HTTPException(status_code=401, detail="Invalid Telegram secret token")

    payload = await request.json() if not body else json.loads(body)
    message = payload.get("message", {})
    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id", "unknown")

    if text.startswith("/initiate_acp"):
        parts = text.split()
        if len(parts) > 1:
            target_url = parts[1]
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-telegram",
                role="user",
                content=f"ACP triggered from Telegram chat {chat_id} for {target_url}",
            )
            logger.info("Gateway (Telegram): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored", "text": text}


# ---------------------------------------------------------------------------
# Discord
# ---------------------------------------------------------------------------


@router.post("/discord/webhook")
async def discord_webhook(
    request: Request,
    x_signature_256: str = Header(None),
) -> dict[str, Any]:
    """
    Hermes-style multi-channel gateway — Discord.

    Validates HMAC-SHA256 signature and handles:
    - ``/status``: returns recent swarm transcript hits from EdgeMemoryDB.
    - ``/initiate_acp <url>``: same trigger as Telegram.

    Requires ``DISCORD_WEBHOOK_SECRET`` env var. Endpoint refuses requests
    when the secret is unset (no fail-open).
    """
    settings = get_settings()
    body = await request.body()

    if not settings.discord_webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="Discord webhook secret not configured -- endpoint disabled",
        )
    if not x_signature_256:
        raise HTTPException(status_code=401, detail="Missing X-Signature-256 header")
    if not _verify_hmac(body, x_signature_256, settings.discord_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid Discord webhook signature")

    payload = json.loads(body)
    content = payload.get("content", "").strip()

    if content.startswith("/status"):
        query = content.removeprefix("/status").strip() or "acp"
        hits = memory_store.fts_search(query, limit=5)
        return {
            "status": "success",
            "query": query,
            "results": hits,
        }

    if content.startswith("/initiate_acp"):
        parts = content.split()
        if len(parts) > 1:
            target_url = parts[1]
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-discord",
                role="user",
                content=f"ACP triggered from Discord for {target_url}",
            )
            logger.info("Gateway (Discord): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored", "content": content}


# ---------------------------------------------------------------------------
# Slack
# ---------------------------------------------------------------------------


@router.post("/slack/webhook")
async def slack_webhook(
    request: Request,
    x_slack_signature: str = Header(None),
    x_slack_request_timestamp: str = Header(None),
) -> dict[str, Any]:
    """
    Hermes-style multi-channel gateway — Slack.

    Validates Slack's v0 HMAC-SHA256 signature with timestamp replay protection
    (rejects requests older than 5 minutes), then routes slash commands.
    """
    import time as _time

    settings = get_settings()
    _require_secret("SLACK_SIGNING_SECRET", settings.slack_signing_secret)
    body = await request.body()

    if not x_slack_signature or not x_slack_request_timestamp:
        raise HTTPException(status_code=401, detail="Missing Slack signature headers")

    # Replay protection: reject timestamps > 5 minutes old
    try:
        ts = int(x_slack_request_timestamp)
        if abs(_time.time() - ts) > 300:
            raise HTTPException(status_code=401, detail="Slack request timestamp too old")
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Slack timestamp") from exc

    sig_base = f"v0:{x_slack_request_timestamp}:{body.decode()}"
    expected = (
        "v0="
        + hmac.new(
            settings.slack_signing_secret.encode(), sig_base.encode(), hashlib.sha256
        ).hexdigest()
    )
    if not hmac.compare_digest(expected, x_slack_signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    # Slack sends form-encoded payloads for slash commands
    try:
        form = await request.form()
        text = str(form.get("text", "")).strip()
        command = str(form.get("command", ""))
        user_name = str(form.get("user_name", "unknown"))
    except Exception:
        payload = json.loads(body)
        text = payload.get("text", "")
        command = payload.get("command", "")
        user_name = payload.get("user_name", "unknown")

    if "/initiate_acp" in command or text.startswith("initiate_acp"):
        target_url = text.strip().split()[0] if text.strip() else ""
        if not target_url:
            return {"response_type": "ephemeral", "text": "Usage: /initiate_acp <url>"}

        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-slack",
            role="user",
            content=f"ACP triggered from Slack by @{user_name} for {target_url}",
        )
        logger.info("Gateway (Slack): ACP triggered for %s → task %s", target_url, task.id)
        return {
            "response_type": "ephemeral",
            "text": f"✅ ACP initiated for `{target_url}` (Task `{task.id}`)",
        }

    return {"response_type": "ephemeral", "text": "Unknown command. Try `/initiate_acp <url>`"}


# ---------------------------------------------------------------------------
# Email (SendGrid / Postmark inbound parse)
# ---------------------------------------------------------------------------


@router.post("/email/inbound")
async def email_inbound(request: Request) -> dict[str, Any]:
    """
    Accepts inbound email parse payloads from SendGrid or Postmark.
    Routes commands from whitelisted sender addresses.
    """
    settings = get_settings()
    payload = await request.json()

    # SendGrid uses 'from', Postmark uses 'From'
    sender = payload.get("from") or payload.get("From", "")
    body_text = payload.get("text") or payload.get("TextBody", "")

    whitelist = [s.strip() for s in settings.gateway_email_whitelist.split(",") if s.strip()]
    if whitelist and sender not in whitelist:
        logger.warning("Gateway (Email): rejected sender %s — not in whitelist.", sender)
        raise HTTPException(status_code=403, detail="Sender not authorised")

    for line in body_text.splitlines():
        line = line.strip()
        if line.lower().startswith("initiate_acp:"):
            target_url = line.split(":", 1)[1].strip()
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-email",
                role="user",
                content=f"ACP triggered via email from {sender} for {target_url}",
            )
            logger.info("Gateway (Email): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ---------------------------------------------------------------------------
# Gap 8 — Wave 2 Gateway Platforms
# ---------------------------------------------------------------------------

# ── WhatsApp (Meta Cloud API) ───────────────────────────────────────────────


@router.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(
    request: Request,
) -> Any:
    """
    Responds to the Meta webhook verification challenge (GET request).
    Required during webhook registration in Meta Developer Portal.
    """
    settings = get_settings()
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == settings.whatsapp_verify_token:
        logger.info("Gateway (WhatsApp): webhook verification successful.")
        from fastapi.responses import PlainTextResponse

        return PlainTextResponse(content=challenge or "")
    raise HTTPException(status_code=403, detail="WhatsApp webhook verification failed")


@router.post("/whatsapp/webhook")
async def whatsapp_inbound(request: Request) -> dict[str, Any]:
    """
    Receive inbound WhatsApp messages via Meta Cloud API webhook.
    Validates X-Hub-Signature-256 and routes /acp commands.

    Requires ``WHATSAPP_ACCESS_TOKEN`` env var (used as the HMAC secret).
    Endpoint refuses requests when the secret is unset.
    """
    settings = get_settings()
    body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")

    if not settings.whatsapp_access_token:
        raise HTTPException(
            status_code=503,
            detail="WhatsApp access token not configured -- endpoint disabled",
        )
    if not _verify_hmac(body, sig, settings.whatsapp_access_token):
        raise HTTPException(status_code=401, detail="Invalid WhatsApp webhook signature")

    try:
        payload = await request.json()
        entry = payload.get("entry", [{}])[0]
        changes = entry.get("changes", [{}])[0]
        message = changes.get("value", {}).get("messages", [{}])[0]
        text = message.get("text", {}).get("body", "")
        from_number = message.get("from", "unknown")
    except Exception:
        return {"status": "ignored"}

    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-whatsapp",
            role="user",
            content=f"ACP triggered via WhatsApp from {from_number} for {target_url}",
        )
        logger.info("Gateway (WhatsApp): ACP triggered for %s → task %s", target_url, task.id)
        return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ── Matrix / Element (Appservice API) ──────────────────────────────────────


@router.put("/matrix/webhook")
@router.post("/matrix/webhook")
async def matrix_inbound(
    request: Request,
    authorization: str = Header(None),
) -> dict[str, Any]:
    """
    Receive events from a Matrix appservice registration.
    Validates the Authorization: Bearer <token> header.
    """
    settings = get_settings()
    _require_secret("MATRIX_APPSERVICE_TOKEN", settings.matrix_appservice_token)
    if authorization != f"Bearer {settings.matrix_appservice_token}":
        raise HTTPException(status_code=401, detail="Invalid Matrix appservice token")

    try:
        payload = await request.json()
        events = payload.get("events", [])
    except Exception:
        return {"status": "ignored"}

    for event in events:
        if event.get("type") != "m.room.message":
            continue
        content = event.get("content", {})
        msgtype = content.get("msgtype")
        if msgtype != "m.text":
            continue

        text = content.get("body", "")
        sender = event.get("sender", "unknown")

        if text.lower().startswith("acp "):
            target_url = text[4:].strip()
            target_url = _validate_webhook_url(target_url)
            task = run_acp_workflow_task.delay(target_url)
            memory_store.insert_transcript(
                run_id=task.id,
                agent_role="gateway-matrix",
                role="user",
                content=f"ACP triggered via Matrix from {sender} for {target_url}",
            )
            logger.info("Gateway (Matrix): ACP triggered for %s → task %s", target_url, task.id)
            return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ── Mattermost (Slash Command) ──────────────────────────────────────────────


@router.post("/mattermost/webhook")
async def mattermost_inbound(request: Request) -> dict[str, Any]:
    """
    Receive Mattermost slash command: /initiate_acp <url>.
    Validates the shared mattermost_token from the request body.
    """
    settings = get_settings()
    _require_secret("MATTERMOST_TOKEN", settings.mattermost_token)
    try:
        form = await request.form()
        token = form.get("token", "")
        text = form.get("text", "")
        user_name = form.get("user_name", "unknown")
    except Exception:
        return {"status": "ignored"}

    if not hmac.compare_digest(str(token), settings.mattermost_token):
        raise HTTPException(status_code=401, detail="Invalid Mattermost token")

    target_url = text.strip()
    if not target_url:
        return {"response_type": "ephemeral", "text": "Usage: /initiate_acp <target-url>"}

    target_url = _validate_webhook_url(target_url)
    task = run_acp_workflow_task.delay(target_url)
    memory_store.insert_transcript(
        run_id=task.id,
        agent_role="gateway-mattermost",
        role="user",
        content=f"ACP triggered via Mattermost by {user_name} for {target_url}",
    )
    logger.info("Gateway (Mattermost): ACP triggered for %s → task %s", target_url, task.id)
    return {
        "response_type": "ephemeral",
        "text": f"✅ ACP run queued (`{task.id}`). Phase I analysis starting for `{target_url}`.",
    }


# ── Signal (via signal-cli REST API) ───────────────────────────────────────


@router.post("/signal/webhook")
async def signal_inbound(request: Request) -> dict[str, Any]:
    """
    Receive inbound Signal messages via signal-cli REST API envelope format.
    Validates source number against the configured whitelist.
    """
    settings = get_settings()
    allowed = {n.strip() for n in settings.signal_allowed_numbers.split(",") if n.strip()}

    try:
        payload = await request.json()
        envelope = payload.get("envelope", {})
        source = envelope.get("source", "")
        data_message = envelope.get("dataMessage", {})
        text = data_message.get("message", "")
    except Exception:
        return {"status": "ignored"}

    if allowed and source not in allowed:
        logger.warning("Gateway (Signal): rejected message from non-whitelisted source %s", source)
        raise HTTPException(status_code=403, detail="Signal source not in allowlist")

    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-signal",
            role="user",
            content=f"ACP triggered via Signal from {source} for {target_url}",
        )
        logger.info("Gateway (Signal): ACP triggered for %s → task %s", target_url, task.id)
        return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ---------------------------------------------------------------------------
# SMS (Twilio)
# ---------------------------------------------------------------------------


@router.post("/sms/inbound")
async def sms_inbound(
    request: Request,
    x_twilio_signature: str = Header(None),
) -> dict[str, Any]:
    """
    Accepts Twilio SMS webhook payloads.
    Validates the X-Twilio-Signature HMAC and routes commands.
    """
    settings = get_settings()
    _require_secret("TWILIO_AUTH_TOKEN", settings.twilio_auth_token)
    body = await request.body()

    try:
        from urllib.parse import parse_qs

        form_data = parse_qs(body.decode(), keep_blank_values=True)
        # Twilio signature = HMAC-SHA1 of URL + sorted params
        url = str(request.url)
        params = "".join(f"{k}{v[0]}" for k, v in sorted(form_data.items()))
        sig_base = (url + params).encode()
        expected = base64.b64encode(
            hmac.new(
                settings.twilio_auth_token.encode(),
                sig_base,
                hashlib.sha1,
            ).digest()
        ).decode()
        if not hmac.compare_digest(expected, x_twilio_signature or ""):
            raise HTTPException(status_code=401, detail="Invalid Twilio signature")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Twilio signature check error: %s", exc)
        raise HTTPException(status_code=401, detail="Twilio signature parse failed") from exc

    try:
        from urllib.parse import parse_qs

        form = parse_qs(body.decode())
        sms_body = form.get("Body", [""])[0].strip()
        from_number = form.get("From", ["unknown"])[0]
    except Exception:
        return {"status": "ignored"}

    if sms_body.lower().startswith("acp "):
        target_url = sms_body[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-sms",
            role="user",
            content=f"ACP triggered via SMS from {from_number} for {target_url}",
        )
        logger.info("Gateway (SMS): ACP triggered for %s → task %s", target_url, task.id)
        return {"status": "success", "action": "acp_triggered", "task_id": task.id}

    return {"status": "ignored"}


# ===========================================================================
# Gateway Wave 3 — 9 additional platform adapters (Track C)
# Completes 18/18 platform coverage matching Hermes Agent
# ===========================================================================


@router.post("/dingtalk/webhook")
async def dingtalk_webhook(request: Request) -> dict[str, Any]:
    """DingTalk inbound webhook — HMAC-SHA256 validated."""
    settings = get_settings()
    _require_secret("DINGTALK_APP_SECRET", getattr(settings, "dingtalk_app_secret", None))
    await request.body()
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")

    string_to_sign = f"{timestamp}\n{settings.dingtalk_app_secret}"
    expected = base64.b64encode(
        hmac.new(
            settings.dingtalk_app_secret.encode(),
            string_to_sign.encode(),
            hashlib.sha256,
        ).digest()
    ).decode()
    if not hmac.compare_digest(expected, sign):
        raise HTTPException(status_code=401, detail="Invalid DingTalk signature")
    try:
        data = await request.json()
        text = data.get("text", {}).get("content", "").strip()
        sender = data.get("senderNick", "unknown")
    except Exception:
        return {"msgtype": "text", "text": {"content": "Parse error"}}
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        memory_store.insert_transcript(
            run_id=task.id,
            agent_role="gateway-dingtalk",
            role="user",
            content=f"ACP from DingTalk ({sender}): {target_url}",
        )
        logger.info("Gateway (DingTalk): ACP -> task %s", task.id)
        return {"msgtype": "text", "text": {"content": f"ACP task started: {task.id}"}}
    return {"msgtype": "text", "text": {"content": "Send: acp <url>"}}


@router.post("/feishu/webhook")
async def feishu_webhook(request: Request) -> dict[str, Any]:
    """Feishu (Lark) event webhook — challenge verification + ACP routing."""
    try:
        data = await request.json()
    except Exception:
        return {"code": 1}
    if data.get("type") == "url_verification":
        return {"challenge": data.get("challenge")}
    settings = get_settings()
    _require_secret("FEISHU_APP_SECRET", getattr(settings, "feishu_app_secret", None))
    body = await request.body()

    ts = request.headers.get("X-Lark-Request-Timestamp", "")
    nonce = request.headers.get("X-Lark-Request-Nonce", "")
    sig = request.headers.get("X-Lark-Signature", "")
    sig_input = f"{ts}{nonce}{settings.feishu_app_secret}{body.decode()}"
    computed = hashlib.sha256(sig_input.encode()).hexdigest()
    if not hmac.compare_digest(computed, sig):
        raise HTTPException(status_code=401, detail="Invalid Feishu signature")
    event = data.get("event", {})
    content_str = event.get("message", {}).get("content", "{}")
    try:
        import json as _j

        text = _j.loads(content_str).get("text", "").strip()
    except Exception:
        text = ""
    if text.lower().startswith("/acp "):
        target_url = text[5:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (Feishu): ACP -> task %s", task.id)
    return {"code": 0}


@router.post("/wecom/webhook")
async def wecom_webhook(request: Request) -> dict[str, Any]:
    """WeCom outgoing webhook — token-validated."""
    settings = get_settings()
    _require_secret("WECOM_TOKEN", getattr(settings, "wecom_token", None))
    token = request.query_params.get("token", "")
    if not hmac.compare_digest(settings.wecom_token, token):
        raise HTTPException(status_code=401, detail="Invalid WeCom token")
    try:
        data = await request.json()
        text = data.get("text", {}).get("content", "").strip()
    except Exception:
        return {"errcode": 1, "errmsg": "parse error"}
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (WeCom): ACP -> task %s", task.id)
    return {"errcode": 0, "errmsg": "ok"}


@router.post("/wecom/callback")
async def wecom_callback(request: Request, echostr: str = None) -> Any:
    """WeCom server-mode callback — echoes challenge, logs encrypted messages."""
    if echostr:
        return echostr
    body = await request.body()
    logger.info("Gateway (WeCom Callback): received %d byte payload", len(body))
    return "<xml><return_code>SUCCESS</return_code></xml>"


@router.post("/weixin/webhook")
async def weixin_webhook(request: Request) -> dict[str, Any]:
    """Weixin via WxPusher — appToken validated."""
    settings = get_settings()
    _require_secret("WEIXIN_APP_TOKEN", getattr(settings, "weixin_app_token", None))
    token = request.query_params.get("appToken", "")
    if not hmac.compare_digest(settings.weixin_app_token, token):
        raise HTTPException(status_code=401, detail="Invalid Weixin appToken")
    try:
        data = await request.json()
        content = data.get("content", "").strip()
    except Exception:
        return {"success": False}
    if content.lower().startswith("acp "):
        target_url = content[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (Weixin): ACP -> task %s", task.id)
        return {"success": True, "task_id": task.id}
    return {"success": True}


@router.post("/bluebubbles/webhook")
async def bluebubbles_webhook(request: Request) -> dict[str, Any]:
    """BlueBubbles iMessage bridge webhook — password validated."""
    settings = get_settings()
    _require_secret("BLUEBUBBLES_PASSWORD", getattr(settings, "bluebubbles_password", None))
    auth = request.headers.get("Authorization", "")
    if not hmac.compare_digest(f"Basic {settings.bluebubbles_password}", auth.strip()):
        raise HTTPException(status_code=401, detail="Invalid BlueBubbles password")
    try:
        data = await request.json()
        text = data.get("data", {}).get("text", "").strip()
    except Exception:
        return {"status": "ignored"}
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (BlueBubbles): ACP -> task %s", task.id)
        return {"status": "ok", "task_id": task.id}
    return {"status": "ignored"}


@router.post("/homeassistant/webhook")
async def homeassistant_webhook(request: Request) -> dict[str, Any]:
    """Home Assistant webhook — Bearer long-lived token validated."""
    settings = get_settings()
    _require_secret("HA_TOKEN", getattr(settings, "ha_token", None))
    bearer = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(settings.ha_token, bearer):
        raise HTTPException(status_code=401, detail="Invalid HA token")
    try:
        data = await request.json()
        message = data.get("message", "").strip()
        entity_id = data.get("entity_id", "unknown")
    except Exception:
        return {"result": "ignored"}
    if message.lower().startswith("acp "):
        target_url = message[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (HomeAssistant): entity=%s -> task %s", entity_id, task.id)
        return {"result": "triggered", "task_id": task.id}
    return {"result": "ignored"}


@router.post("/webhook/{channel_id}")
async def generic_webhook(
    channel_id: str,
    request: Request,
    x_webhook_signature: str = None,
) -> dict[str, Any]:
    """Generic HMAC-signed webhook. channel_id used for routing/logging.

    Requires ``AUTOSWARM_WEBHOOK_SECRET`` env var. Endpoint refuses requests
    when the secret is unset OR when the X-Webhook-Signature header is missing
    (no fail-open).
    """
    body = await request.body()
    from ..config import get_settings as _get_settings

    secret = _get_settings().autoswarm_webhook_secret
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="Generic webhook secret not configured -- endpoint disabled",
        )
    if not x_webhook_signature:
        raise HTTPException(status_code=401, detail="Missing X-Webhook-Signature header")
    if not _verify_hmac(body, x_webhook_signature, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        import json as _j

        data = _j.loads(body)
    except Exception:
        data = {}
    text = (data.get("text") or data.get("message") or data.get("content") or "").strip()
    if text.lower().startswith("acp "):
        target_url = text[4:].strip()
        target_url = _validate_webhook_url(target_url)
        task = run_acp_workflow_task.delay(target_url)
        logger.info("Gateway (Webhook/%s): ACP -> task %s", channel_id, task.id)
        return {"status": "ok", "channel_id": channel_id, "task_id": task.id}
    return {"status": "ignored", "channel_id": channel_id}


@router.post("/api/complete")
async def api_complete(request: Request) -> dict[str, Any]:
    """Direct API completion — fire-and-forget ACP dispatch. Mirrors Hermes api_server mode."""
    if not request.headers.get("Authorization", "").startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid JSON body") from exc
    target_url: str = data.get("target_url", "")
    metadata: dict = data.get("metadata", {})
    if not target_url:
        raise HTTPException(status_code=422, detail="target_url is required")
    target_url = _validate_webhook_url(target_url)
    task = run_acp_workflow_task.delay(target_url, metadata=metadata)
    logger.info("Gateway (API): ACP for %s -> task %s", target_url, task.id)
    return {
        "status": "dispatched",
        "task_id": task.id,
        "target_url": target_url,
        "poll_url": f"/api/v1/acp/status/{task.id}",
    }
