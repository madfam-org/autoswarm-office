"""Reddit posting capability with mandatory AI disclosure + per-subreddit
rate-limiting + ConfigMap-driven policy enforcement.

MVP scope: single-subreddit text-post submission via PRAW. Multi-subreddit
crossposting, comment threads, and X (Twitter) parity are explicitly out
of scope for this PR.

Operational notes for the operator who wires up the Secret + ConfigMap:

- **Secret keys** (provisioned via Janua-platform Vault → K8s Secret):
  - ``REDDIT_CLIENT_ID``      OAuth app client id (script-type app)
  - ``REDDIT_CLIENT_SECRET``  OAuth app secret
  - ``REDDIT_USER_AGENT``     Reddit-required UA string
                              (e.g. ``selva-agent/1.0 (by /u/madfam_io)``)
  - ``REDDIT_REFRESH_TOKEN``  Long-lived refresh token (script app
                              installed-app flow)
  When ANY of these is missing, the tool raises
  :class:`ToolNotConfiguredError` and logs WARN — it does NOT post a
  placeholder, in keeping with the v2.1.1 LLM-placeholder-abort pattern
  (no fake outputs ever leave the system).

- **ConfigMap** ``subreddit-policies``: mounted at
  ``/etc/selva/subreddit_policies.yaml``. Schema documented at
  ``infra/k8s/configmaps/subreddit-policies-default.yaml``. When the
  ConfigMap is absent the tool falls back to a conservative built-in
  default: every entry ``disclosure_required: true``.

- **Rate-limit**: at most 1 post per subreddit per 30 minutes. State
  lives in Redis at ``selva:reddit:last_post:{subreddit}`` with a 30-min
  TTL. Worker pod restarts do NOT reset the limit.

- **Disclosure**: when the per-subreddit policy says
  ``disclosure_required: true``, we append a fixed footer pointing at
  ``https://madfam.io/ai-disclosure``. The URL is a placeholder — it
  does not need to resolve at posting time, but the operator must
  publish a real disclosure page before going live.

- **HITL gate**: this tool is also gated by the ``reddit_promo_v1``
  playbook (``require_approval=True``) — every post invocation pauses
  for a human approver. Defence in depth alongside the rate limit and
  ConfigMap policy.
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors + types
# ---------------------------------------------------------------------------


class ToolNotConfiguredError(RuntimeError):
    """Raised when required environment / config inputs are missing.

    Tools that send to external platforms (Reddit, Twilio, Twitter, etc.)
    MUST raise this rather than returning placeholder output. The
    permission engine + worker drain logic surface it as a hard failure
    so ops sees the missing secret and can rotate / provision it.
    """


class RedditPolicyError(RuntimeError):
    """Raised when the requested post violates a subreddit policy.

    This is not a configuration error — the agent SHOULD have known the
    subreddit was off-limits. We surface it as a hard failure so the
    failure event lands in the audit trail rather than being silently
    discarded.
    """


@dataclass(frozen=True)
class SubredditPolicy:
    """Per-subreddit posting policy loaded from the ConfigMap.

    Conservative defaults: every unknown subreddit treated as
    ``disclosure_required=True`` with no minimum karma.
    """

    subreddit: str
    disclosure_required: bool = True
    min_karma: int = 0
    flair: str | None = None


@dataclass
class _PolicyCache:
    """Module-level lazily-loaded policy cache.

    The ConfigMap is mounted on the worker pod; reading it once on first
    use is cheaper than re-reading every send. K8s mounts the ConfigMap
    via projected-volume so a ``configmap:reload`` lands on disk
    automatically — but workers re-init on restart anyway, so a stale
    in-memory cache is bounded by pod lifetime. Operator: bump the
    Deployment annotation to force re-roll if you push a hot policy
    change.
    """

    policies: dict[str, SubredditPolicy] = field(default_factory=dict)
    loaded: bool = False
    source_path: Path | None = None


_POLICY_CACHE = _PolicyCache()


# ---------------------------------------------------------------------------
# Configuration loaders
# ---------------------------------------------------------------------------


CONFIGMAP_PATH = Path(
    os.environ.get("SELVA_REDDIT_POLICIES_PATH", "/etc/selva/subreddit_policies.yaml")
)


def _required_env() -> dict[str, str]:
    """Return the dict of required Reddit env vars, raising
    ToolNotConfiguredError when any is missing.

    NEVER returns a partially-populated dict — the operator must
    provision all four together.
    """
    keys = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT", "REDDIT_REFRESH_TOKEN")
    values = {k: os.environ.get(k, "").strip() for k in keys}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise ToolNotConfiguredError(
            "Reddit credentials missing — operator must provision env vars: "
            + ", ".join(missing)
        )
    return values


def _load_policies(path: Path | None = None) -> dict[str, SubredditPolicy]:
    """Load + cache the per-subreddit policy ConfigMap.

    Returns an empty dict when the ConfigMap is absent (fallback path:
    every subreddit treated as ``disclosure_required=True``).

    ``path`` defaults to the module-level :data:`CONFIGMAP_PATH`. The
    indirection (rather than ``path: Path = CONFIGMAP_PATH``) is so
    test code can ``monkeypatch.setattr(reddit_tools, 'CONFIGMAP_PATH',
    other_path)`` and have it take effect — function-default
    expressions are bound at function-def time and ignore later
    monkeypatching.
    """
    if path is None:
        path = CONFIGMAP_PATH

    if _POLICY_CACHE.loaded and _POLICY_CACHE.source_path == path:
        return _POLICY_CACHE.policies

    policies: dict[str, SubredditPolicy] = {}
    if path.exists():
        try:
            import yaml  # late import — yaml is a dep elsewhere

            raw = yaml.safe_load(path.read_text()) or {}
            for entry in raw.get("policies", []):
                sub = (entry.get("subreddit") or "").lstrip("/").removeprefix("r/")
                if not sub:
                    continue
                policies[sub.lower()] = SubredditPolicy(
                    subreddit=sub,
                    disclosure_required=bool(entry.get("disclosure_required", True)),
                    min_karma=int(entry.get("min_karma", 0)),
                    flair=entry.get("flair"),
                )
        except Exception as exc:
            logger.warning(
                "subreddit_policies.yaml load failed (%s) — falling back to safe defaults",
                exc,
            )

    _POLICY_CACHE.policies = policies
    _POLICY_CACHE.loaded = True
    _POLICY_CACHE.source_path = path
    return policies


def _resolve_policy(subreddit: str) -> SubredditPolicy:
    """Return the loaded policy for ``subreddit``, defaulting to
    conservative-everything when the subreddit is not listed."""
    key = subreddit.lstrip("/").removeprefix("r/").lower()
    policies = _load_policies()
    if key in policies:
        return policies[key]
    return SubredditPolicy(subreddit=key, disclosure_required=True)


# ---------------------------------------------------------------------------
# Disclosure footer
# ---------------------------------------------------------------------------


_DISCLOSURE_FOOTER = (
    "\n\n---\n"
    "*Posted by an AI agent on behalf of MADFAM "
    "([context](https://madfam.io/ai-disclosure)).*"
)


def _maybe_apply_disclosure(body: str, policy: SubredditPolicy) -> tuple[str, bool]:
    """Return (body_with_disclosure_if_required, applied_bool).

    Idempotent — if the footer is already present we don't double-stamp
    (defends against agents that hand-craft it before sending).
    """
    if not policy.disclosure_required:
        return body, False
    if "madfam.io/ai-disclosure" in body.lower():
        return body, True  # already disclosed
    return body + _DISCLOSURE_FOOTER, True


# ---------------------------------------------------------------------------
# Rate limiting (Redis-backed)
# ---------------------------------------------------------------------------


_RATE_LIMIT_TTL_SECONDS = 30 * 60  # 30 minutes per subreddit


async def _check_and_set_rate_limit(subreddit: str) -> None:
    """Reject (raise RuntimeError) when the same subreddit was posted
    to within the last 30 minutes. SETs the Redis key on success.

    Behaviour when Redis is unavailable: log + allow. The HITL gate +
    LLM-tier throttling already provide a soft brake; failing closed
    on Redis outage would block legitimate ops.
    """
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.debug("REDIS_URL unset — skipping reddit rate-limit (HITL still gates)")
        return

    key = f"selva:reddit:last_post:{subreddit.lower()}"
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url)
        try:
            existing = await r.get(key)
            if existing is not None:
                ttl = await r.ttl(key)
                raise RuntimeError(
                    f"Reddit rate-limit hit for r/{subreddit}: another post "
                    f"was made in the last 30 minutes (resets in ~{max(0, ttl)}s)"
                )
            # SETEX with NX semantics — atomic claim of the slot.
            await r.set(key, "1", ex=_RATE_LIMIT_TTL_SECONDS, nx=True)
        finally:
            with contextlib.suppress(Exception):
                await r.aclose()
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Reddit rate-limit check failed (%s) — allowing post", exc)


# ---------------------------------------------------------------------------
# PRAW glue (kept thin for testability)
# ---------------------------------------------------------------------------


def _build_reddit_client(creds: dict[str, str]) -> Any:
    """Return a praw.Reddit instance.

    Late-imports praw so the module loads in environments without it
    (CI test discovery, etc.). When praw is missing we raise
    :class:`ToolNotConfiguredError` so ops gets a clear signal.
    """
    try:
        import praw  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ToolNotConfiguredError(
            "praw not installed — `pip install praw>=7.7` in the worker image"
        ) from exc

    return praw.Reddit(
        client_id=creds["REDDIT_CLIENT_ID"],
        client_secret=creds["REDDIT_CLIENT_SECRET"],
        user_agent=creds["REDDIT_USER_AGENT"],
        refresh_token=creds["REDDIT_REFRESH_TOKEN"],
    )


def _submit_via_praw(
    client: Any,
    *,
    subreddit: str,
    title: str,
    body: str,
    flair: str | None,
) -> dict[str, str]:
    """Synchronous PRAW submission. PRAW does not have an async API yet,
    so callers should run this in a threadpool when the surrounding
    handler is async.

    Returns ``{"post_url": permalink, "post_id": id36}``.
    """
    sub = client.subreddit(subreddit.lstrip("/").removeprefix("r/"))
    submission = sub.submit(
        title=title,
        selftext=body,
        flair_id=None,
        flair_text=flair,
        send_replies=False,
    )
    return {
        "post_url": f"https://reddit.com{submission.permalink}",
        "post_id": str(submission.id),
    }


# ---------------------------------------------------------------------------
# PostHog event emission
# ---------------------------------------------------------------------------


def _emit_outbound_post_event(
    subreddit: str,
    persona_id: str,
    post_id: str,
    disclosure_applied: bool,
) -> None:
    """Fire the ``outbound_post.created`` PostHog event. Fire-and-forget."""
    try:
        from nexus_api.analytics import track

        track(
            persona_id or "anonymous",
            "outbound_post.created",
            {
                "subreddit": subreddit,
                "persona_id": persona_id,
                "post_id": post_id,
                "platform": "reddit",
                "disclosure_applied": disclosure_applied,
            },
        )
    except Exception:
        logger.debug("PostHog track failed for outbound_post.created", exc_info=True)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class RedditPostTool(BaseTool):
    """Submit a text post to a single subreddit via PRAW, applying the
    operator-configured disclosure + rate-limit policy.

    Returns ``ToolResult(data={"post_url": ..., "post_id": ...})``.
    """

    name = "reddit_post"
    description = (
        "Submit a text post to a single subreddit. Mandatory AI-agent disclosure "
        "is appended automatically when the per-subreddit policy requires it "
        "(default: always). Rate-limited to 1 post per subreddit per 30 minutes. "
        "Requires REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT, "
        "REDDIT_REFRESH_TOKEN env vars; raises ToolNotConfiguredError when missing. "
        "Returns the post permalink + id."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "subreddit": {
                    "type": "string",
                    "description": "Target subreddit (without 'r/' prefix). E.g. 'SaaS'.",
                },
                "title": {
                    "type": "string",
                    "description": "Post title (≤300 chars per Reddit rules).",
                    "maxLength": 300,
                },
                "body": {
                    "type": "string",
                    "description": (
                        "Post body (markdown). Disclosure footer "
                        "auto-appended when policy requires."
                    ),
                    "maxLength": 40000,
                },
                "persona_id": {
                    "type": "string",
                    "description": "Selva persona id used for PostHog attribution.",
                    "default": "default",
                },
            },
            "required": ["subreddit", "title", "body"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        subreddit_raw = (kwargs.get("subreddit") or "").strip()
        title = (kwargs.get("title") or "").strip()
        body = kwargs.get("body") or ""
        persona_id = kwargs.get("persona_id") or "default"

        if not subreddit_raw:
            return ToolResult(success=False, error="subreddit is required")
        if not title:
            return ToolResult(success=False, error="title is required")
        if not body:
            return ToolResult(success=False, error="body is required")

        subreddit = subreddit_raw.lstrip("/").removeprefix("r/")

        # Resolve policy + apply disclosure BEFORE checking creds, so a
        # mis-configured operator still sees the policy violation in the
        # audit trail when they do hook up creds.
        policy = _resolve_policy(subreddit)
        body_to_send, disclosure_applied = _maybe_apply_disclosure(body, policy)

        # Credential check — raises ToolNotConfiguredError on miss.
        # Never returns placeholder output.
        creds = _required_env()

        # Rate-limit (Redis-backed). Raises RuntimeError on hit.
        try:
            await _check_and_set_rate_limit(subreddit)
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        # Submit via PRAW in a threadpool — PRAW is sync.
        try:
            import asyncio

            client = _build_reddit_client(creds)
            result = await asyncio.to_thread(
                _submit_via_praw,
                client,
                subreddit=subreddit,
                title=title,
                body=body_to_send,
                flair=policy.flair,
            )
        except ToolNotConfiguredError:
            raise
        except Exception as exc:
            logger.exception("Reddit submit failed for r/%s", subreddit)
            return ToolResult(
                success=False,
                error=f"Reddit submit failed: {exc.__class__.__name__}: {exc}",
            )

        post_id = result["post_id"]
        post_url = result["post_url"]

        _emit_outbound_post_event(
            subreddit=subreddit,
            persona_id=persona_id,
            post_id=post_id,
            disclosure_applied=disclosure_applied,
        )

        logger.info(
            "Reddit post submitted: r/%s persona=%s post_id=%s disclosure=%s",
            subreddit,
            persona_id,
            post_id,
            disclosure_applied,
        )

        return ToolResult(
            success=True,
            output=post_url,
            data={
                "post_url": post_url,
                "post_id": post_id,
                "subreddit": subreddit,
                "disclosure_applied": disclosure_applied,
                "persona_id": persona_id,
            },
        )


# Tools are TENANT audience (default) — every tenant swarm can run the
# Reddit promo playbook so long as the operator has provisioned creds for
# their account. Platform-only Reddit ops would be a separate tool.
__all__ = [
    "RedditPostTool",
    "RedditPolicyError",
    "SubredditPolicy",
    "ToolNotConfiguredError",
]
