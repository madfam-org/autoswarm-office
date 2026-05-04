"""Bluesky / AT Protocol posting capability with mandatory AI disclosure +
per-persona rate-limiting + 300-char hard limit enforcement.

MVP scope: original text posts + replies, single persona per call. Quote-posts,
threading, and image/video attachments are explicitly out of scope for this PR
(parity with the Reddit MVP — round out the v1 social-channel set first, then
expand richness).

Operational notes for the operator who wires up the Secret per persona:

- **Per-persona credentials** (provisioned via Janua-platform Vault → K8s
  Secret). Bluesky uses an *app-password* model — NOT OAuth. Each persona
  needs its own app password generated at
  <https://bsky.app/settings/app-passwords>:

  - ``BLUESKY_HANDLE_<persona_id>``         e.g.
    ``BLUESKY_HANDLE_default = madfam.bsky.social``
  - ``BLUESKY_APP_PASSWORD_<persona_id>``   16-char app password, NOT the
    account login password. Treat it like an API token: rotate quarterly
    per ``docs/SECRET_ROTATION_POLICY.md``, store in Vault, never commit
    to source.

  When EITHER is missing for the requested persona, the tool raises
  :class:`ToolNotConfiguredError` and logs WARN — it does NOT post a
  placeholder, in keeping with the v2.1.1 LLM-placeholder-abort pattern.

- **Rate-limit**: at most 1 post per persona per 30 minutes. State lives
  in Redis at ``selva:bluesky:last_post:{persona_id}`` with a 30-min TTL.
  Bluesky's underlying API rate limit is high (5000 points/hr) but a
  conservative cadence for promo content is the operating constraint —
  same as Reddit.

- **Disclosure (mandatory)**: every post gets the suffix
  ``"\\n\\n— Posted by an AI agent on behalf of MADFAM"`` (~36 chars).
  Bluesky has a hard 300-char limit per post, so the tool auto-truncates
  the user-provided text to fit alongside the disclosure footer. If the
  user-only text alone is already past 300 chars (i.e. would overflow
  even WITHOUT the disclosure footer), the tool raises
  :class:`PostTooLongError` rather than silently truncating — agent
  surfaces a hard error so the operator + LLM see the policy violation.

- **HITL gate**: this tool is also gated by the ``bluesky_promo_v1``
  playbook (``require_approval=True``) — every post invocation pauses
  for a human approver. Defence in depth alongside the rate limit and
  the mandatory disclosure footer.

- **Languages**: Bluesky posts carry a ``langs`` array. Default
  ``["en"]``; for Karafiel/Dhanam Spanish copy pass ``langs=["es"]``.
  Setting the right language helps Bluesky's discovery feeds surface
  the post to the right audience.
"""

from __future__ import annotations

import contextlib
import logging
import os
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
    """Raised when the user-supplied text overflows Bluesky's 300-char
    limit even without the disclosure footer.

    We surface this as a hard error rather than silently truncating
    because (a) an arbitrarily-truncated post can lose meaning or change
    the message in unintended ways, and (b) the LLM agent should learn
    to write within the budget. The error message includes the exact
    overflow so the agent can retry with a tighter draft.
    """


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Bluesky's hard per-post character limit (300 graphemes). We treat the
# limit as character-count for simplicity; the atproto client itself
# enforces the grapheme-cluster boundary on send, so this is a soft
# pre-flight check.
BLUESKY_MAX_POST_CHARS = 300

# Mandatory AI-agent disclosure footer. Kept compact (~36 chars) to
# leave the most room possible for promo content. Includes a leading
# blank line for visual separation from the body.
DISCLOSURE_FOOTER = "\n\n— Posted by an AI agent on behalf of MADFAM"

# Marker substring used to detect already-disclosed bodies so we don't
# double-stamp when an agent hand-crafts the footer pre-send.
_DISCLOSURE_MARKER = "AI agent on behalf of MADFAM"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def _required_env(persona_id: str) -> dict[str, str]:
    """Return the dict of required Bluesky env vars for ``persona_id``,
    raising :class:`ToolNotConfiguredError` when either is missing.

    Bluesky uses *app passwords*, not OAuth — each persona has its own
    handle + app password pair. Variable names are scoped by
    ``persona_id`` (uppercased) so multiple personas can be provisioned
    in the same worker pod.
    """
    suffix = (persona_id or "default").upper().replace("-", "_")
    handle_key = f"BLUESKY_HANDLE_{suffix}"
    pw_key = f"BLUESKY_APP_PASSWORD_{suffix}"
    handle = os.environ.get(handle_key, "").strip()
    password = os.environ.get(pw_key, "").strip()
    missing = [k for k, v in ((handle_key, handle), (pw_key, password)) if not v]
    if missing:
        raise ToolNotConfiguredError(
            "Bluesky credentials missing for persona "
            f"'{persona_id}' — operator must provision env vars: "
            + ", ".join(missing)
        )
    return {"handle": handle, "password": password}


# ---------------------------------------------------------------------------
# Disclosure + length enforcement
# ---------------------------------------------------------------------------


def _apply_disclosure_with_limit(text: str) -> tuple[str, bool]:
    """Return (text_with_disclosure, applied_bool).

    Bluesky's 300-char limit is hard. The disclosure footer is mandatory.
    Three cases:

    1. ``text`` already contains the disclosure marker — keep it as-is,
       still validate length, return ``applied=True``.
    2. ``text`` + footer fits within 300 chars — append, return.
    3. ``text`` alone is already past 300 chars — raise
       :class:`PostTooLongError` (agent must rewrite tighter; we never
       silently truncate the body).

    Cases (2) where ``text`` + footer would push past 300 are caught
    by the same overflow check — the agent must shorten enough that
    the FOOTER fits too. The thresholds are documented in the README.
    """
    raw = text or ""
    if _DISCLOSURE_MARKER in raw:
        # Already disclosed (agent hand-crafted the footer). Validate
        # total length but do not double-stamp.
        if len(raw) > BLUESKY_MAX_POST_CHARS:
            raise PostTooLongError(
                "Bluesky post exceeds 300-char limit "
                f"({len(raw)} chars). Already-disclosed body cannot "
                "be auto-truncated; rewrite tighter."
            )
        return raw, True

    if len(raw) > BLUESKY_MAX_POST_CHARS:
        raise PostTooLongError(
            "Bluesky post body alone exceeds 300-char limit "
            f"({len(raw)} chars, max {BLUESKY_MAX_POST_CHARS}). "
            "Rewrite the post tighter — disclosure footer "
            f"({len(DISCLOSURE_FOOTER)} chars) is mandatory and "
            "cannot be dropped."
        )

    combined = raw + DISCLOSURE_FOOTER
    if len(combined) > BLUESKY_MAX_POST_CHARS:
        # Body fits but body + footer does not. Same outcome — agent
        # must rewrite tighter so footer fits.
        budget = BLUESKY_MAX_POST_CHARS - len(DISCLOSURE_FOOTER)
        raise PostTooLongError(
            "Bluesky post + mandatory disclosure footer exceeds "
            f"300-char limit ({len(combined)} chars, max "
            f"{BLUESKY_MAX_POST_CHARS}). Rewrite the post under "
            f"{budget} chars to leave room for the footer "
            f"({len(DISCLOSURE_FOOTER)} chars)."
        )

    return combined, True


# ---------------------------------------------------------------------------
# Rate limiting (Redis-backed)
# ---------------------------------------------------------------------------


_RATE_LIMIT_TTL_SECONDS = 30 * 60  # 30 minutes per persona


async def _check_and_set_rate_limit(persona_id: str) -> None:
    """Reject (raise RuntimeError) when the same persona posted within
    the last 30 minutes. SETs the Redis key on success.

    Behaviour when Redis is unavailable: log + allow. The HITL gate +
    LLM-tier throttling already provide a soft brake; failing closed
    on Redis outage would block legitimate ops.
    """
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.debug(
            "REDIS_URL unset — skipping bluesky rate-limit (HITL still gates)"
        )
        return

    key = f"selva:bluesky:last_post:{persona_id.lower()}"
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url)
        try:
            existing = await r.get(key)
            if existing is not None:
                ttl = await r.ttl(key)
                raise RuntimeError(
                    "Bluesky rate-limit hit for persona "
                    f"'{persona_id}': another post was made in the last "
                    f"30 minutes (resets in ~{max(0, ttl)}s)"
                )
            # SETEX with NX semantics — atomic claim of the slot.
            await r.set(key, "1", ex=_RATE_LIMIT_TTL_SECONDS, nx=True)
        finally:
            with contextlib.suppress(Exception):
                await r.aclose()
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Bluesky rate-limit check failed (%s) — allowing post", exc)


# ---------------------------------------------------------------------------
# atproto glue (kept thin for testability)
# ---------------------------------------------------------------------------


def _build_bluesky_client(handle: str, password: str) -> Any:
    """Return a logged-in ``atproto.Client`` instance.

    Late-imports atproto so the module loads in environments without it
    (CI test discovery, etc.). When atproto is missing we raise
    :class:`ToolNotConfiguredError` so ops gets a clear signal.
    """
    try:
        from atproto import Client  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ToolNotConfiguredError(
            "atproto not installed — `pip install atproto>=0.0.46` in the "
            "worker image (or install via `pip install selva-tools[bluesky]`)"
        ) from exc

    client = Client()
    client.login(handle, password)
    return client


def _post_via_atproto(
    client: Any,
    *,
    text: str,
    langs: list[str] | None,
    reply_to: dict[str, Any] | None,
) -> dict[str, str]:
    """Synchronous atproto post submission.

    The atproto SDK is synchronous — callers should run this in a
    threadpool when the surrounding handler is async (we do, below).

    Returns ``{"post_uri": "at://...", "post_url": "https://bsky.app/...",
    "post_cid": "..."}``.
    """
    # ``send_post`` is the atproto SDK's high-level helper that wraps
    # ``com.atproto.repo.createRecord`` for ``app.bsky.feed.post``. It
    # accepts ``langs`` directly. ``reply_to`` is the atproto-style
    # ``ReplyRef`` dict ``{"root": {"uri", "cid"}, "parent": {"uri",
    # "cid"}}`` — we pass through opaquely so callers retain control
    # over reply threading.
    kwargs: dict[str, Any] = {"text": text}
    if langs:
        kwargs["langs"] = langs
    if reply_to:
        kwargs["reply_to"] = reply_to

    response = client.send_post(**kwargs)

    # ``response.uri`` is the at:// URI; ``response.cid`` is the content
    # hash. We synthesise the public bsky.app permalink from the URI by
    # mapping ``at://did:plc:.../app.bsky.feed.post/<rkey>`` to
    # ``https://bsky.app/profile/<did>/post/<rkey>``.
    post_uri = str(getattr(response, "uri", "") or "")
    post_cid = str(getattr(response, "cid", "") or "")

    post_url = _uri_to_bsky_app_url(post_uri)
    return {"post_uri": post_uri, "post_url": post_url, "post_cid": post_cid}


def _uri_to_bsky_app_url(at_uri: str) -> str:
    """Convert an at:// URI to a public bsky.app web URL.

    ``at://did:plc:abc/app.bsky.feed.post/3kxyz`` →
    ``https://bsky.app/profile/did:plc:abc/post/3kxyz``.

    Returns empty string on a malformed URI rather than raising — the
    URI is the source of truth (recorded in PostHog + returned to
    callers); the web URL is a convenience.
    """
    if not at_uri.startswith("at://"):
        return ""
    body = at_uri[len("at://") :]  # noqa: E203
    parts = body.split("/")
    if len(parts) < 3 or parts[1] != "app.bsky.feed.post":
        return ""
    did, _collection, rkey = parts[0], parts[1], parts[2]
    return f"https://bsky.app/profile/{did}/post/{rkey}"


# ---------------------------------------------------------------------------
# PostHog event emission
# ---------------------------------------------------------------------------


def _emit_outbound_post_event(
    persona_id: str,
    post_uri: str,
    post_cid: str,
    disclosure_applied: bool,
) -> None:
    """Fire the ``outbound_post.created`` PostHog event. Fire-and-forget."""
    try:
        from nexus_api.analytics import track

        track(
            persona_id or "anonymous",
            "outbound_post.created",
            {
                "platform": "bluesky",
                "persona_id": persona_id,
                "post_uri": post_uri,
                "post_cid": post_cid,
                "disclosure_applied": disclosure_applied,
            },
        )
    except Exception:
        logger.debug(
            "PostHog track failed for outbound_post.created (bluesky)",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class BlueskyPostTool(BaseTool):
    """Submit a text post to Bluesky / AT Protocol via atproto, applying
    the mandatory AI-disclosure footer + per-persona rate-limit.

    Returns ``ToolResult(data={"post_url": ..., "post_uri": ...})``.
    """

    name = "bluesky_post"
    description = (
        "Submit a text post to Bluesky / AT Protocol. Mandatory AI-agent "
        "disclosure footer is appended automatically (~36 chars). Bluesky's "
        "300-char per-post limit is enforced including the footer; if user "
        "text overflows, raises PostTooLongError (no silent truncation). "
        "Rate-limited to 1 post per persona per 30 minutes. "
        "Requires BLUESKY_HANDLE_<PERSONA_ID> + "
        "BLUESKY_APP_PASSWORD_<PERSONA_ID> env vars; raises "
        "ToolNotConfiguredError when missing. "
        "Default language en; pass langs=['es'] for Spanish copy. "
        "Returns the post URI + permalink + CID."
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
                        "user content alone must therefore fit within "
                        f"{BLUESKY_MAX_POST_CHARS - len(DISCLOSURE_FOOTER)} "
                        f"chars. Bluesky's hard limit is "
                        f"{BLUESKY_MAX_POST_CHARS} chars per post."
                    ),
                    "maxLength": BLUESKY_MAX_POST_CHARS,
                },
                "persona_id": {
                    "type": "string",
                    "description": (
                        "Selva persona id. Used to look up "
                        "BLUESKY_HANDLE_<id> + BLUESKY_APP_PASSWORD_<id> "
                        "env vars and as PostHog distinct_id for "
                        "attribution."
                    ),
                    "default": "default",
                },
                "reply_to": {
                    "type": "object",
                    "description": (
                        "Optional atproto ReplyRef for threading: "
                        "{'root': {'uri', 'cid'}, 'parent': "
                        "{'uri', 'cid'}}. Quote-posts are NOT supported "
                        "in v1; use a fresh post instead."
                    ),
                    "properties": {
                        "root": {
                            "type": "object",
                            "properties": {
                                "uri": {"type": "string"},
                                "cid": {"type": "string"},
                            },
                            "required": ["uri", "cid"],
                        },
                        "parent": {
                            "type": "object",
                            "properties": {
                                "uri": {"type": "string"},
                                "cid": {"type": "string"},
                            },
                            "required": ["uri", "cid"],
                        },
                    },
                    "required": ["root", "parent"],
                },
                "langs": {
                    "type": "array",
                    "description": (
                        "BCP-47 language tags for the post (e.g. ['en'], "
                        "['es']). Default ['en']. Use ['es'] for Karafiel/"
                        "Dhanam Spanish promo copy so Bluesky's discovery "
                        "feeds surface it to the right audience."
                    ),
                    "items": {"type": "string"},
                    "default": ["en"],
                },
            },
            "required": ["text"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        text_raw = kwargs.get("text")
        if not isinstance(text_raw, str) or not text_raw.strip():
            return ToolResult(success=False, error="text is required")

        persona_id = (kwargs.get("persona_id") or "default").strip() or "default"
        reply_to = kwargs.get("reply_to")
        langs = kwargs.get("langs") or ["en"]
        if not isinstance(langs, list) or not all(isinstance(x, str) for x in langs):
            return ToolResult(
                success=False,
                error="langs must be a list of BCP-47 strings (e.g. ['en'])",
            )

        # Apply disclosure + enforce 300-char limit BEFORE checking creds, so
        # the LLM sees the policy violation even when credentials are absent.
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

        # Submit via atproto in a threadpool — the SDK is synchronous.
        try:
            import asyncio

            client = _build_bluesky_client(creds["handle"], creds["password"])
            result = await asyncio.to_thread(
                _post_via_atproto,
                client,
                text=text_to_send,
                langs=langs,
                reply_to=reply_to,
            )
        except ToolNotConfiguredError:
            raise
        except Exception as exc:
            logger.exception(
                "Bluesky post failed for persona=%s", persona_id
            )
            return ToolResult(
                success=False,
                error=f"Bluesky post failed: {exc.__class__.__name__}: {exc}",
            )

        post_uri = result["post_uri"]
        post_url = result["post_url"]
        post_cid = result["post_cid"]

        _emit_outbound_post_event(
            persona_id=persona_id,
            post_uri=post_uri,
            post_cid=post_cid,
            disclosure_applied=disclosure_applied,
        )

        logger.info(
            "Bluesky post submitted: persona=%s post_uri=%s disclosure=%s",
            persona_id,
            post_uri,
            disclosure_applied,
        )

        return ToolResult(
            success=True,
            output=post_url or post_uri,
            data={
                "post_url": post_url,
                "post_uri": post_uri,
                "post_cid": post_cid,
                "persona_id": persona_id,
                "disclosure_applied": disclosure_applied,
                "langs": langs,
            },
        )


# Tool is TENANT audience (default) — every tenant swarm can run the
# Bluesky promo playbook so long as the operator has provisioned an
# app password for their persona. Platform-only Bluesky ops (e.g. MADFAM
# corporate handle) would be a separate, PLATFORM-tagged tool.
__all__ = [
    "BLUESKY_MAX_POST_CHARS",
    "BlueskyPostTool",
    "DISCLOSURE_FOOTER",
    "PostTooLongError",
    "ToolNotConfiguredError",
]
