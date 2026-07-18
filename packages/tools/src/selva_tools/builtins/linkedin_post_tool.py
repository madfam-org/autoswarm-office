"""LinkedIn DIRECT-POST capability — SHIPS DARK (disabled by default).

Relationship to ``linkedin_drafts.py`` (READ THIS FIRST)
=======================================================

``linkedin_drafts.py`` states that a ``linkedin_post`` tool "should be
rejected" because "LinkedIn has no automation-friendly promo-posting API"
without partnership status MADFAM does not hold. That is accurate for the
**Marketing Developer Platform** (ads, advanced analytics, scheduled
company-page campaigns) — but it is NOT the whole picture for basic
organic posting:

- LinkedIn's **Posts API** (``POST /rest/posts``) lets a *standard* app
  publish a member or organization post using an OAuth 2.0 access token
  carrying the ``w_member_social`` scope (member posts) or
  ``w_organization_social`` scope (company-page posts). Those scopes are
  obtainable via the "Share on LinkedIn" / "Sign In with LinkedIn"
  products — an operator OAuth authorization, NOT a partnership.

So the honest position is: direct LinkedIn posting IS possible, but only
with the OPERATOR's own LinkedIn app + an access token they authorize.
This module scaffolds that path. It does NOT replace the draft tool —
``linkedin_draft_create`` remains the default, zero-config path. This tool:

- **Ships dark.** Disabled unless ``SELVA_LINKEDIN_POST_ENABLED`` is truthy
  (``1``/``true``/``yes``/``on``). Until then ``execute()`` returns a failed
  ``ToolResult`` with a clear "disabled / drafts are the default" message —
  never a crash, never a fake success.
- **Fails closed on missing credentials.** Once enabled, absent env vars
  raise :class:`ToolNotConfiguredError` (Reddit/Mastodon/Bluesky pattern) —
  no placeholder output.
- **Stubs the real API-call shape with a TODO.** ``_build_linkedin_client``
  + ``_post_via_linkedin`` carry the intended Posts-API call so the authed
  request is a single documented edit. The network call is only reached with
  the flag on, credentials present, and ``httpx`` available. See the
  ``TODO(linkedin-api)`` marker.

Disclosure policy — WHY this differs from the draft tool
--------------------------------------------------------

``linkedin_drafts.py`` deliberately OMITS the AI-disclosure footer because a
HUMAN copy-pastes the draft, so the post is the human's own content. This
tool posts AUTOMATICALLY end-to-end, so — per MADFAM's AI-disclosure policy
(same rationale as Reddit/Mastodon/Bluesky) — it MUST disclose. The
distinction is exactly the human-in-the-loop step the draft module calls
out. The footer is mandatory here; it is not on the draft path.

Operational notes for the operator who wires up the Secret per persona
----------------------------------------------------------------------

- **Per-persona credentials** (provisioned via Janua-platform Vault → K8s
  Secret), scoped by persona id (upper-cased, non-alphanumerics →
  underscores):

  - ``LINKEDIN_ACCESS_TOKEN_<persona_id>``  OAuth 2.0 access token with the
    ``w_member_social`` (member) or ``w_organization_social`` (org) scope.
    Tokens are relatively short-lived — rotate per ``SECRET_ROTATION_POLICY``.
  - ``LINKEDIN_AUTHOR_URN_<persona_id>``    the author URN the post is
    attributed to, e.g. ``urn:li:person:<id>`` or
    ``urn:li:organization:<id>``.

  When EITHER is missing for the requested persona (with the flag ON), the
  tool raises :class:`ToolNotConfiguredError` and logs WARN.

- **Rate-limit**: at most 1 post per persona per 30 minutes, Redis key
  ``selva:linkedin:last_post:{persona_id}``.

- **HITL gate**: gated by the ``linkedin_promo_v1`` playbook
  (``require_approval=True``) — every post pauses for a human approver.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ToolNotConfiguredError(RuntimeError):
    """Raised when required env / config inputs are missing.

    Tools that send to external platforms MUST raise this rather than
    returning placeholder output so ops sees the missing secret.
    """


class PostTooLongError(ValueError):
    """Raised when the post body overflows LinkedIn's character limit even
    without the disclosure footer — surfaced instead of silent truncation."""


# ---------------------------------------------------------------------------
# Constants + feature flag
# ---------------------------------------------------------------------------


# Feature flag env var. OFF by default — the tool ships dark; drafts remain
# the default LinkedIn path. Truthy: 1/true/yes/on.
LINKEDIN_POST_ENABLED_ENV = "SELVA_LINKEDIN_POST_ENABLED"

# LinkedIn's hard per-post limit for text posts is 3000 chars.
LINKEDIN_MAX_POST_CHARS = 3000

# Mandatory AI-agent disclosure footer for AUTOMATED posts (see module
# docstring: the draft path omits this because a human posts it; this path
# posts automatically, so disclosure is required).
DISCLOSURE_FOOTER = "\n\nPosted by an AI agent on behalf of MADFAM."

_DISCLOSURE_MARKER = "AI agent on behalf of MADFAM"

_RATE_LIMIT_TTL_SECONDS = 30 * 60  # 30 minutes per persona

_TRUTHY = frozenset({"1", "true", "yes", "on"})

# LinkedIn API version header (monthly-versioned REST API). Bump when the
# operator upgrades; kept here so the version bump is one edit.
LINKEDIN_API_VERSION = "202405"
LINKEDIN_POSTS_ENDPOINT = "https://api.linkedin.com/rest/posts"


def _is_enabled() -> bool:
    """Return True only when the operator has armed the LinkedIn integration.
    Default (env unset) is False — ships dark."""
    return os.environ.get(LINKEDIN_POST_ENABLED_ENV, "").strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _persona_env_suffix(persona_id: str) -> str:
    """Map a persona id to its env-var suffix: upper-case, non-alphanumerics
    → underscores. Mirrors Mastodon/X."""
    return re.sub(r"[^A-Z0-9]+", "_", (persona_id or "default").upper()).strip("_") or "DEFAULT"


def _required_env(persona_id: str) -> dict[str, str]:
    """Return the required LinkedIn env vars for ``persona_id``, raising
    :class:`ToolNotConfiguredError` when either is missing. NEVER returns a
    partially-populated dict."""
    suffix = _persona_env_suffix(persona_id)
    token_key = f"LINKEDIN_ACCESS_TOKEN_{suffix}"
    urn_key = f"LINKEDIN_AUTHOR_URN_{suffix}"
    values = {
        token_key: os.environ.get(token_key, "").strip(),
        urn_key: os.environ.get(urn_key, "").strip(),
    }
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise ToolNotConfiguredError(
            "LinkedIn credentials missing for persona "
            f"'{persona_id}' — operator must provision env vars: " + ", ".join(missing)
        )
    return {"access_token": values[token_key], "author_urn": values[urn_key]}


# ---------------------------------------------------------------------------
# Disclosure + length enforcement
# ---------------------------------------------------------------------------


def _apply_disclosure_with_limit(text: str) -> tuple[str, bool]:
    """Return (text_with_disclosure, applied_bool).

    LinkedIn's 3000-char limit is hard; the disclosure footer is mandatory
    for automated posts. Raises :class:`PostTooLongError` on overflow —
    never silently truncates.
    """
    raw = text or ""
    if _DISCLOSURE_MARKER in raw:
        if len(raw) > LINKEDIN_MAX_POST_CHARS:
            raise PostTooLongError(
                "LinkedIn post exceeds 3000-char limit "
                f"({len(raw)} chars). Already-disclosed body cannot be "
                "auto-truncated; rewrite tighter."
            )
        return raw, True

    if len(raw) > LINKEDIN_MAX_POST_CHARS:
        raise PostTooLongError(
            "LinkedIn post body alone exceeds 3000-char limit "
            f"({len(raw)} chars, max {LINKEDIN_MAX_POST_CHARS}). Rewrite "
            f"tighter — disclosure footer ({len(DISCLOSURE_FOOTER)} chars) "
            "is mandatory for automated posts."
        )

    combined = raw + DISCLOSURE_FOOTER
    if len(combined) > LINKEDIN_MAX_POST_CHARS:
        budget = LINKEDIN_MAX_POST_CHARS - len(DISCLOSURE_FOOTER)
        raise PostTooLongError(
            "LinkedIn post + mandatory disclosure footer exceeds 3000-char "
            f"limit ({len(combined)} chars, max {LINKEDIN_MAX_POST_CHARS}). "
            f"Rewrite the post under {budget} chars to leave room for the "
            f"footer ({len(DISCLOSURE_FOOTER)} chars)."
        )
    return combined, True


# ---------------------------------------------------------------------------
# Rate limiting (Redis-backed) — mirrors the other social tools
# ---------------------------------------------------------------------------


async def _check_and_set_rate_limit(persona_id: str) -> None:
    """Reject (raise RuntimeError) when the same persona posted within the
    last 30 minutes. SETs the Redis key on success. Redis unavailable →
    log + allow (HITL still gates)."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.debug("REDIS_URL unset — skipping linkedin rate-limit (HITL still gates)")
        return

    key = f"selva:linkedin:last_post:{persona_id.lower()}"
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url)
        try:
            existing = await r.get(key)
            if existing is not None:
                ttl = await r.ttl(key)
                raise RuntimeError(
                    "LinkedIn rate-limit hit for persona "
                    f"'{persona_id}': another post was made in the last "
                    f"30 minutes (resets in ~{max(0, ttl)}s)"
                )
            await r.set(key, "1", ex=_RATE_LIMIT_TTL_SECONDS, nx=True)
        finally:
            with contextlib.suppress(Exception):
                await r.aclose()
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("LinkedIn rate-limit check failed (%s) — allowing post", exc)


# ---------------------------------------------------------------------------
# LinkedIn Posts API glue (STUBBED — real authed call carries a TODO marker)
# ---------------------------------------------------------------------------


def _build_linkedin_client(creds: dict[str, str]) -> Any:
    """Return an ``httpx.Client`` pre-loaded with the LinkedIn auth headers.

    Late-imports ``httpx`` so the module loads where it isn't installed. When
    ``httpx`` is missing we raise :class:`ToolNotConfiguredError` (same shape
    as the Bluesky/Mastodon client builders)."""
    try:
        import httpx
    except ImportError as exc:
        raise ToolNotConfiguredError(
            "httpx not installed — required for the LinkedIn Posts API call; "
            "`pip install httpx` in the worker image before enabling "
            "SELVA_LINKEDIN_POST_ENABLED"
        ) from exc

    return httpx.Client(
        headers={
            "Authorization": f"Bearer {creds['access_token']}",
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "X-Restli-Protocol-Version": "2.0.0",
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


def _post_via_linkedin(client: Any, *, text: str, author_urn: str) -> dict[str, str]:
    """Publish a text post via the LinkedIn Posts API. Returns
    ``{"post_id": "urn:li:share:...", "post_url": "..."}``."""
    body = {
        "author": author_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    # TODO(linkedin-api): confirmed shape for the versioned Posts API is
    # ``POST https://api.linkedin.com/rest/posts`` with the JSON body above;
    # the created post URN is returned in the ``x-restli-id`` response header
    # (there is no JSON body on 201). This module ships dark
    # (SELVA_LINKEDIN_POST_ENABLED off by default) and this path is only
    # reached with the flag on, real creds present, and httpx installed.
    # Verify the header name + URN→permalink mapping against the deployed
    # LinkedIn-Version when the operator first arms the integration, then
    # delete this TODO.
    response = client.post(LINKEDIN_POSTS_ENDPOINT, json=body)
    response.raise_for_status()
    post_id = str(response.headers.get("x-restli-id") or "")
    post_url = f"https://www.linkedin.com/feed/update/{post_id}" if post_id else ""
    return {"post_id": post_id, "post_url": post_url}


# ---------------------------------------------------------------------------
# PostHog event emission
# ---------------------------------------------------------------------------


def _emit_outbound_post_event(persona_id: str, post_id: str, disclosure_applied: bool) -> None:
    """Fire the ``outbound_post.created`` PostHog event. Fire-and-forget."""
    try:
        from nexus_api.analytics import track

        track(
            persona_id or "anonymous",
            "outbound_post.created",
            {
                "platform": "linkedin",
                "persona_id": persona_id,
                "post_id": post_id,
                "disclosure_applied": disclosure_applied,
            },
        )
    except Exception:
        logger.debug("PostHog track failed for outbound_post.created (linkedin)", exc_info=True)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class LinkedInPostTool(BaseTool):
    """Publish a post to LinkedIn via the Posts API — SHIPS DARK.

    Disabled by default (drafts via ``linkedin_draft_create`` remain the
    default path): returns a failed ``ToolResult`` until the operator sets
    ``SELVA_LINKEDIN_POST_ENABLED`` truthy AND provisions credentials.
    Applies the mandatory AI-disclosure footer (automated posts) + per-persona
    30-min rate-limit and is HITL-gated by ``linkedin_promo_v1``.
    """

    name = "linkedin_post"
    description = (
        "Publish a text post to LinkedIn via the Posts API. SHIPS DARK — "
        "disabled unless the operator sets SELVA_LINKEDIN_POST_ENABLED and "
        "provisions credentials; returns a failed ToolResult when "
        "disabled/unconfigured (never a fake success). Drafts "
        "(linkedin_draft_create) remain the default path. Mandatory AI-agent "
        "disclosure footer auto-appended (automated posts must disclose); "
        "3000-char limit enforced including the footer. Rate-limited to 1 post "
        "per persona per 30 minutes. Requires "
        "LINKEDIN_ACCESS_TOKEN_<persona_id> (w_member_social / "
        "w_organization_social scope) and LINKEDIN_AUTHOR_URN_<persona_id>; "
        "raises ToolNotConfiguredError when missing once enabled."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Post body / commentary. Mandatory AI-agent disclosure "
                        f"footer (~{len(DISCLOSURE_FOOTER)} chars) is "
                        "auto-appended; user content alone must fit within "
                        f"{LINKEDIN_MAX_POST_CHARS - len(DISCLOSURE_FOOTER)} "
                        f"chars. LinkedIn's hard limit is "
                        f"{LINKEDIN_MAX_POST_CHARS} chars."
                    ),
                    "maxLength": LINKEDIN_MAX_POST_CHARS,
                },
                "persona_id": {
                    "type": "string",
                    "description": (
                        "Selva persona id. Selects the per-persona access "
                        "token + author URN (LINKEDIN_ACCESS_TOKEN_<id> / "
                        "LINKEDIN_AUTHOR_URN_<id>) and tags PostHog "
                        "attribution."
                    ),
                    "default": "default",
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        text_raw = kwargs.get("text")
        if not isinstance(text_raw, str) or not text_raw.strip():
            return ToolResult(success=False, error="text is required")

        persona_id = (kwargs.get("persona_id") or "default").strip() or "default"

        # ---- Feature-flag gate (ships dark) — fail closed, never crash ----
        if not _is_enabled():
            return ToolResult(
                success=False,
                error=(
                    "linkedin_post is disabled (ships dark); use "
                    "linkedin_draft_create for the default manual-paste path. "
                    f"To post directly the operator must set "
                    f"{LINKEDIN_POST_ENABLED_ENV}=true and provision "
                    "LINKEDIN_ACCESS_TOKEN_<persona> (w_member_social / "
                    "w_organization_social) + LINKEDIN_AUTHOR_URN_<persona>."
                ),
            )

        # Apply disclosure + enforce 3000-char limit BEFORE checking creds.
        try:
            text_to_send, disclosure_applied = _apply_disclosure_with_limit(text_raw)
        except PostTooLongError as exc:
            return ToolResult(success=False, error=str(exc))

        # Credential check — raises ToolNotConfiguredError on miss.
        creds = _required_env(persona_id)

        # Rate-limit (Redis-backed). Raises RuntimeError on hit.
        try:
            await _check_and_set_rate_limit(persona_id)
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        # Submit via the Posts API in a threadpool — httpx.Client is sync.
        try:
            import asyncio

            client = _build_linkedin_client(creds)
            result = await asyncio.to_thread(
                _post_via_linkedin,
                client,
                text=text_to_send,
                author_urn=creds["author_urn"],
            )
        except ToolNotConfiguredError:
            raise
        except Exception as exc:
            logger.exception("LinkedIn post failed for persona=%s", persona_id)
            return ToolResult(
                success=False,
                error=f"LinkedIn post failed: {exc.__class__.__name__}: {exc}",
            )

        post_id = result["post_id"]
        post_url = result["post_url"]

        _emit_outbound_post_event(
            persona_id=persona_id,
            post_id=post_id,
            disclosure_applied=disclosure_applied,
        )

        logger.info(
            "LinkedIn post submitted: persona=%s post_id=%s disclosure=%s",
            persona_id,
            post_id,
            disclosure_applied,
        )

        return ToolResult(
            success=True,
            output=post_url or post_id,
            data={
                "post_url": post_url,
                "post_id": post_id,
                "persona_id": persona_id,
                "disclosure_applied": disclosure_applied,
            },
        )


# Tool is TENANT audience (default) — every tenant swarm can run the LinkedIn
# promo playbook once the operator has armed the flag + provisioned a
# per-persona token + author URN. Platform-only LinkedIn ops would be a
# separate, PLATFORM-tagged tool.
__all__ = [
    "DISCLOSURE_FOOTER",
    "LINKEDIN_MAX_POST_CHARS",
    "LINKEDIN_POST_ENABLED_ENV",
    "LinkedInPostTool",
    "PostTooLongError",
    "ToolNotConfiguredError",
]
