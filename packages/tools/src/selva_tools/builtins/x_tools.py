"""X (Twitter) posting capability — SHIPS DARK (disabled by default).

Parity scaffold for the ``mastodon_post`` / ``bluesky_post`` executors, so
X/Twitter is a config-flip away rather than a from-scratch build. It is
NOT wired into any enabled-by-default send path:

- **Feature-flagged OFF by default.** The tool only attempts a post when
  ``SELVA_X_POST_ENABLED`` is truthy (``1``/``true``/``yes``/``on``). Until
  the operator sets it, ``execute()`` returns a failed ``ToolResult`` with a
  clear "disabled / ships dark" message — never a crash, never a fake
  success. This is the deliberate "ships dark" gate: the integration is
  present and testable, but inert until an operator turns it on AND
  provisions credentials.
- **Fail-closed on missing credentials.** Once enabled, if the required
  env vars are absent the tool raises :class:`ToolNotConfiguredError`
  (identical to the Reddit/Mastodon/Bluesky pattern) — it does NOT post a
  placeholder.
- **Real API-call shape stubbed with a TODO.** ``_build_x_client`` +
  ``_post_via_x`` carry the intended X API v2 (``tweepy``) call shape so
  the authed client call is a single documented edit. The actual network
  call is only reached when the flag is on, credentials are present, AND
  ``tweepy`` is installed in the worker image — none of which hold by
  default. See the ``TODO(x-api)`` marker in ``_post_via_x``.

Honest limitation
-----------------

Posting to X requires the OPERATOR's own X developer app + per-account
user tokens (OAuth 1.0a user context, the auth mode ``POST /2/tweets``
needs when tweeting on behalf of an account). This module cannot post
without them; it scaffolds the integration so that provisioning the app +
tokens and flipping ``SELVA_X_POST_ENABLED`` is all that stands between
here and live posting.

Operational notes for the operator who wires up the Secret per persona
----------------------------------------------------------------------

- **App-level credentials (shared across personas)** — from the operator's
  X developer app (https://developer.x.com), "Keys and tokens":

  - ``X_API_KEY``      OAuth 1.0a consumer key (a.k.a. API key)
  - ``X_API_SECRET``   OAuth 1.0a consumer secret

- **Per-persona user credentials** — each persona posts from a real X
  account; generate a user access token/secret for that account (with
  Read+Write permission) and store scoped by persona id (upper-cased,
  non-alphanumerics → underscores, same rule as Mastodon):

  - ``X_ACCESS_TOKEN_<persona_id>``          user access token
  - ``X_ACCESS_TOKEN_SECRET_<persona_id>``   user access token secret

  When ANY of the four is missing for the requested persona (with the flag
  ON), the tool raises :class:`ToolNotConfiguredError` and logs WARN.

- **Disclosure (mandatory)**: every post gets the AI-agent disclosure
  footer, same policy as Bluesky. X's hard limit is 280 chars; the footer
  is counted against it. If the user text alone overflows 280 the tool
  raises :class:`PostTooLongError` rather than silently truncating.

- **Rate-limit**: at most 1 post per persona per 30 minutes, Redis key
  ``selva:x:last_post:{persona_id}`` (mirrors Bluesky).

- **HITL gate**: gated by the ``x_promo_v1`` playbook
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
    returning placeholder output. The permission engine + worker drain
    logic surface it as a hard failure so ops sees the missing secret
    and can rotate / provision it.
    """


class PostTooLongError(ValueError):
    """Raised when user-supplied text overflows X's 280-char limit even
    without the disclosure footer. Surfaced as a hard error rather than
    silently truncating so the LLM agent rewrites within budget."""


# ---------------------------------------------------------------------------
# Constants + feature flag
# ---------------------------------------------------------------------------


# Feature flag env var. OFF by default — the tool ships dark. Set to a
# truthy value ("1"/"true"/"yes"/"on") to arm the integration (still needs
# credentials, still HITL-gated).
X_POST_ENABLED_ENV = "SELVA_X_POST_ENABLED"

# X's hard per-post character limit (standard accounts). 280 graphemes;
# treated as character-count for a soft pre-flight check.
X_MAX_POST_CHARS = 280

# Mandatory AI-agent disclosure footer. Kept compact (~36 chars). Leading
# blank line separates it from the body. Mirrors the Bluesky footer.
DISCLOSURE_FOOTER = "\n\n— Posted by an AI agent on behalf of MADFAM"

# Marker substring used to detect already-disclosed bodies (no double-stamp).
_DISCLOSURE_MARKER = "AI agent on behalf of MADFAM"

_RATE_LIMIT_TTL_SECONDS = 30 * 60  # 30 minutes per persona

_TRUTHY = frozenset({"1", "true", "yes", "on"})


def _is_enabled() -> bool:
    """Return True only when the operator has armed the X integration.

    Default (env unset) is False — the tool ships dark. Truthy values are
    ``1``/``true``/``yes``/``on`` (case-insensitive)."""
    return os.environ.get(X_POST_ENABLED_ENV, "").strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _persona_env_suffix(persona_id: str) -> str:
    """Map a persona id to its env-var suffix: upper-case, non-alphanumerics
    → underscores. ``"growth-bot-1"`` → ``"GROWTH_BOT_1"``. Mirrors Mastodon."""
    return re.sub(r"[^A-Z0-9]+", "_", (persona_id or "default").upper()).strip("_") or "DEFAULT"


def _required_env(persona_id: str) -> dict[str, str]:
    """Return the dict of required X env vars for ``persona_id``, raising
    :class:`ToolNotConfiguredError` when any is missing.

    NEVER returns a partially-populated dict — app-level key/secret AND the
    per-persona user token/secret must all be present together.
    """
    suffix = _persona_env_suffix(persona_id)
    token_key = f"X_ACCESS_TOKEN_{suffix}"
    token_secret_key = f"X_ACCESS_TOKEN_SECRET_{suffix}"
    values = {
        "X_API_KEY": os.environ.get("X_API_KEY", "").strip(),
        "X_API_SECRET": os.environ.get("X_API_SECRET", "").strip(),
        token_key: os.environ.get(token_key, "").strip(),
        token_secret_key: os.environ.get(token_secret_key, "").strip(),
    }
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise ToolNotConfiguredError(
            "X (Twitter) credentials missing for persona "
            f"'{persona_id}' — operator must provision env vars: " + ", ".join(missing)
        )
    return values


# ---------------------------------------------------------------------------
# Disclosure + length enforcement (identical policy to Bluesky)
# ---------------------------------------------------------------------------


def _apply_disclosure_with_limit(text: str) -> tuple[str, bool]:
    """Return (text_with_disclosure, applied_bool).

    X's 280-char limit is hard; the disclosure footer is mandatory.
    Raises :class:`PostTooLongError` when the body (or body+footer)
    overflows — never silently truncates.
    """
    raw = text or ""
    if _DISCLOSURE_MARKER in raw:
        if len(raw) > X_MAX_POST_CHARS:
            raise PostTooLongError(
                "X post exceeds 280-char limit "
                f"({len(raw)} chars). Already-disclosed body cannot be "
                "auto-truncated; rewrite tighter."
            )
        return raw, True

    if len(raw) > X_MAX_POST_CHARS:
        raise PostTooLongError(
            "X post body alone exceeds 280-char limit "
            f"({len(raw)} chars, max {X_MAX_POST_CHARS}). Rewrite tighter — "
            f"disclosure footer ({len(DISCLOSURE_FOOTER)} chars) is mandatory."
        )

    combined = raw + DISCLOSURE_FOOTER
    if len(combined) > X_MAX_POST_CHARS:
        budget = X_MAX_POST_CHARS - len(DISCLOSURE_FOOTER)
        raise PostTooLongError(
            "X post + mandatory disclosure footer exceeds 280-char limit "
            f"({len(combined)} chars, max {X_MAX_POST_CHARS}). Rewrite the "
            f"post under {budget} chars to leave room for the footer "
            f"({len(DISCLOSURE_FOOTER)} chars)."
        )
    return combined, True


# ---------------------------------------------------------------------------
# Rate limiting (Redis-backed) — mirrors bluesky_tools
# ---------------------------------------------------------------------------


async def _check_and_set_rate_limit(persona_id: str) -> None:
    """Reject (raise RuntimeError) when the same persona posted within the
    last 30 minutes. SETs the Redis key on success. Redis unavailable →
    log + allow (HITL still gates)."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.debug("REDIS_URL unset — skipping x rate-limit (HITL still gates)")
        return

    key = f"selva:x:last_post:{persona_id.lower()}"
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url)
        try:
            existing = await r.get(key)
            if existing is not None:
                ttl = await r.ttl(key)
                raise RuntimeError(
                    "X rate-limit hit for persona "
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
        logger.warning("X rate-limit check failed (%s) — allowing post", exc)


# ---------------------------------------------------------------------------
# X API v2 glue (STUBBED — real authed call carries a TODO marker)
# ---------------------------------------------------------------------------


def _build_x_client(creds: dict[str, str], persona_id: str) -> Any:
    """Return an authenticated X API v2 client (``tweepy.Client``).

    Late-imports ``tweepy`` so the module loads in environments without it
    (CI test discovery, worker images that haven't added the dep yet). When
    ``tweepy`` is missing we raise :class:`ToolNotConfiguredError` so ops
    gets a clear signal — same shape as the Bluesky/Mastodon client builders.
    """
    try:
        import tweepy  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ToolNotConfiguredError(
            "tweepy not installed — `pip install tweepy>=4.14` in the worker "
            "image (or install via `pip install selva-tools[x]`) before "
            "enabling SELVA_X_POST_ENABLED"
        ) from exc

    suffix = _persona_env_suffix(persona_id)
    return tweepy.Client(
        consumer_key=creds["X_API_KEY"],
        consumer_secret=creds["X_API_SECRET"],
        access_token=creds[f"X_ACCESS_TOKEN_{suffix}"],
        access_token_secret=creds[f"X_ACCESS_TOKEN_SECRET_{suffix}"],
    )


def _post_via_x(client: Any, *, text: str) -> dict[str, str]:
    """Submit a tweet via the X API v2 and return post identifiers.

    Returns ``{"post_id": "...", "post_url": "https://x.com/i/web/status/..."}``.
    """
    # TODO(x-api): confirmed call shape for tweepy>=4.14 is
    # ``client.create_tweet(text=text)`` returning a ``Response`` whose
    # ``.data`` is ``{"id": "...", "text": "..."}``. This module ships dark
    # (SELVA_X_POST_ENABLED off by default) and this path is only reached
    # with the flag on, real creds present, and tweepy installed. Verify the
    # response field mapping against the deployed tweepy version when the
    # operator first arms the integration, then delete this TODO.
    response = client.create_tweet(text=text)
    data = getattr(response, "data", None) or {}
    post_id = str(data.get("id") or "")
    post_url = f"https://x.com/i/web/status/{post_id}" if post_id else ""
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
                "platform": "x",
                "persona_id": persona_id,
                "post_id": post_id,
                "disclosure_applied": disclosure_applied,
            },
        )
    except Exception:
        logger.debug("PostHog track failed for outbound_post.created (x)", exc_info=True)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class XPostTool(BaseTool):
    """Submit a post to X (Twitter) via the X API v2 — SHIPS DARK.

    Disabled by default: returns a failed ``ToolResult`` until the operator
    sets ``SELVA_X_POST_ENABLED`` truthy AND provisions credentials. Applies
    the mandatory AI-disclosure footer + per-persona 30-min rate-limit and
    is HITL-gated by ``x_promo_v1``. Returns
    ``ToolResult(data={"post_url": ..., "post_id": ...})`` on success.
    """

    name = "x_post"
    description = (
        "Submit a post to X (Twitter). SHIPS DARK — disabled unless the "
        "operator sets SELVA_X_POST_ENABLED and provisions X API credentials; "
        "returns a failed ToolResult when disabled/unconfigured (never a fake "
        "success). Mandatory AI-agent disclosure footer auto-appended (~36 "
        "chars); X's 280-char limit enforced including the footer (raises "
        "PostTooLongError on overflow, no silent truncation). Rate-limited to "
        "1 post per persona per 30 minutes. Requires X_API_KEY, X_API_SECRET, "
        "X_ACCESS_TOKEN_<persona_id>, X_ACCESS_TOKEN_SECRET_<persona_id>; "
        "raises ToolNotConfiguredError when missing once enabled."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "Post body. Mandatory AI-agent disclosure footer "
                        f"(~{len(DISCLOSURE_FOOTER)} chars) is auto-appended; "
                        "user content alone must fit within "
                        f"{X_MAX_POST_CHARS - len(DISCLOSURE_FOOTER)} chars. "
                        f"X's hard limit is {X_MAX_POST_CHARS} chars."
                    ),
                    "maxLength": X_MAX_POST_CHARS,
                },
                "persona_id": {
                    "type": "string",
                    "description": (
                        "Selva persona id. Selects the per-persona user "
                        "tokens (X_ACCESS_TOKEN_<id> / "
                        "X_ACCESS_TOKEN_SECRET_<id>) and tags PostHog "
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
                    "x_post is disabled (ships dark). Operator must set "
                    f"{X_POST_ENABLED_ENV}=true and provision X API "
                    "credentials (X_API_KEY, X_API_SECRET, "
                    "X_ACCESS_TOKEN_<persona>, X_ACCESS_TOKEN_SECRET_<persona>) "
                    "to enable."
                ),
            )

        # Apply disclosure + enforce 280-char limit BEFORE checking creds, so
        # the LLM sees a policy violation even when credentials are absent.
        try:
            text_to_send, disclosure_applied = _apply_disclosure_with_limit(text_raw)
        except PostTooLongError as exc:
            return ToolResult(success=False, error=str(exc))

        # Credential check — raises ToolNotConfiguredError on miss. Never
        # returns placeholder output.
        creds = _required_env(persona_id)

        # Rate-limit (Redis-backed). Raises RuntimeError on hit.
        try:
            await _check_and_set_rate_limit(persona_id)
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        # Submit via the X API v2 in a threadpool — tweepy is synchronous.
        try:
            import asyncio

            client = _build_x_client(creds, persona_id)
            result = await asyncio.to_thread(_post_via_x, client, text=text_to_send)
        except ToolNotConfiguredError:
            raise
        except Exception as exc:
            logger.exception("X post failed for persona=%s", persona_id)
            return ToolResult(
                success=False,
                error=f"X post failed: {exc.__class__.__name__}: {exc}",
            )

        post_id = result["post_id"]
        post_url = result["post_url"]

        _emit_outbound_post_event(
            persona_id=persona_id,
            post_id=post_id,
            disclosure_applied=disclosure_applied,
        )

        logger.info(
            "X post submitted: persona=%s post_id=%s disclosure=%s",
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


# Tool is TENANT audience (default) — every tenant swarm can run the X promo
# playbook once the operator has armed the flag + provisioned per-persona
# tokens. Platform-only X ops would be a separate, PLATFORM-tagged tool.
__all__ = [
    "DISCLOSURE_FOOTER",
    "PostTooLongError",
    "ToolNotConfiguredError",
    "XPostTool",
    "X_MAX_POST_CHARS",
    "X_POST_ENABLED_ENV",
]
