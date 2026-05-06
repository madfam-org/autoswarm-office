"""Mastodon (fediverse) posting capability with mandatory AI disclosure +
per-instance rate-limiting + ConfigMap-driven policy enforcement.

Mirrors the Reddit tool (``reddit_tools.py``) defense-in-depth pattern.
Differences vs. Reddit, called out so the operator + reviewer don't have
to diff the two files line-by-line:

- **Per-persona access tokens.** Mastodon is federated — every persona
  posts from a real account on a real instance. We therefore key the
  access token by ``persona_id`` (env var ``MASTODON_ACCESS_TOKEN_<id>``)
  rather than baking a single org-wide refresh token. The instance URL
  is shared (``MASTODON_INSTANCE_URL``) — most orgs run one Mastodon
  account per persona on a small set of "home" instances.

- **Default visibility = ``unlisted``.** Mastodon visibilities are
  ``public`` / ``unlisted`` / ``private`` / ``direct``. ``unlisted``
  posts are accessible to everyone but do NOT show up on the local /
  federated public timelines. The fediverse social contract is
  significantly more sensitive to "promo posts spamming the public
  timeline" than Reddit's subreddit model — the friction-cost of going
  ``public`` is a moderator-banhammer that takes the persona's account
  with it. We therefore default-down to ``unlisted`` and require an
  explicit ``visibility="public"`` argument to opt back in. Per-instance
  policy (``allowed_visibilities``) bounds this further: a strict
  instance like ``fosstodon.org`` may pin every post to ``unlisted``
  regardless of what the agent asked for.

- **Content warnings.** Mastodon supports a ``spoiler_text`` field that
  collapses the post body behind a "show more" affordance (the
  "content warning" UI). Promo posts that aren't strictly on-topic for
  the instance SHOULD set a CW; we expose the raw field
  (``content_warning``) and let the per-instance policy mark CWs
  mandatory via ``cw_required: true``.

- **Stricter rate-limit on FOSS-leaning instances.** Reddit's rate
  limit was 30 min per subreddit. Fosstodon and similar FOSS-leaning
  instances are even less tolerant of bot accounts; the ConfigMap
  carries a per-instance override (``rate_limit_minutes``, default 30,
  documented bumps for known-strict instances).

Operational notes (operator who wires up the Secret + ConfigMap):

- **Secret keys** (provisioned via Janua-platform Vault → K8s Secret):

  - ``MASTODON_INSTANCE_URL``                   Shared base URL (e.g.
                                                ``https://mastodon.social``)
  - ``MASTODON_ACCESS_TOKEN_<persona_id>``      Per-persona OAuth
                                                access token. Persona id
                                                is upper-cased + non-
                                                alphanumerics replaced
                                                with underscores. So
                                                ``persona_id="growth-bot-1"``
                                                reads from env var
                                                ``MASTODON_ACCESS_TOKEN_GROWTH_BOT_1``.

  When EITHER is missing the tool raises :class:`ToolNotConfiguredError`
  and logs WARN — it does NOT post a placeholder, in keeping with the
  v2.1.1 LLM-placeholder-abort pattern (no fake outputs ever leave the
  system).

- **ConfigMap** ``mastodon-policies``: mounted at
  ``/etc/selva/mastodon_policies.yaml``. Schema documented at
  ``infra/k8s/configmaps/mastodon-policies-default.yaml``. When the
  ConfigMap is absent the tool falls back to a conservative built-in
  default: every instance ``disclosure_required: true``,
  ``allowed_visibilities=["unlisted"]``, ``rate_limit_minutes=30``.

- **Rate-limit**: at most 1 post per instance per 30 minutes (per-
  instance override possible). State lives in Redis at
  ``selva:mastodon:last_post:{instance}`` with the configured TTL.
  Worker pod restarts do NOT reset the limit.

- **Disclosure**: when the per-instance policy says
  ``disclosure_required: true``, we append a fixed footer pointing at
  ``https://madfam.io/ai-disclosure``. Idempotent (no double-stamp).

- **HITL gate**: this tool is also gated by the ``mastodon_promo_v1``
  playbook (``require_approval=True``) — every post invocation pauses
  for a human approver. Defence in depth alongside the rate limit and
  ConfigMap policy.

- **Provisioning per-persona tokens**: each persona registers an OAuth
  app on its target instance via the user's account (``Settings →
  Development → New application``), grants ``write:statuses`` scope,
  and copies the resulting access token into Vault under
  ``mastodon/access_token/<persona_id>``. Selva's Vault → K8s Secret
  sync materialises it as ``MASTODON_ACCESS_TOKEN_<PERSONA_ID>`` on
  the worker Deployment.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
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

    Tools that send to external platforms (Reddit, Mastodon, Twilio, etc.)
    MUST raise this rather than returning placeholder output. The
    permission engine + worker drain logic surface it as a hard failure
    so ops sees the missing secret and can rotate / provision it.
    """


class MastodonPolicyError(RuntimeError):
    """Raised when the requested post violates an instance policy.

    Examples: visibility not in the per-instance allow-list, missing
    content warning when one is mandatory. Surfaced as a hard failure
    so the violation lands in the audit trail.
    """


# Mastodon visibility values — see https://docs.joinmastodon.org/entities/Status/#visibility
_VALID_VISIBILITIES = frozenset({"public", "unlisted", "private", "direct"})

# Conservative defaults if a per-instance policy is missing. ``unlisted``
# is the safe pick: post is accessible by URL but does NOT spam the
# public/federated timelines.
_DEFAULT_ALLOWED_VISIBILITIES: tuple[str, ...] = ("unlisted",)
_DEFAULT_RATE_LIMIT_MINUTES = 30


@dataclass(frozen=True)
class InstancePolicy:
    """Per-instance posting policy loaded from the ConfigMap.

    Conservative defaults: every unknown instance treated as
    ``disclosure_required=True``, only ``unlisted`` visibility allowed,
    30-min rate limit.
    """

    instance: str
    disclosure_required: bool = True
    allowed_visibilities: tuple[str, ...] = _DEFAULT_ALLOWED_VISIBILITIES
    rate_limit_minutes: int = _DEFAULT_RATE_LIMIT_MINUTES
    cw_required: bool = False
    max_chars: int = 500  # Mastodon default; some instances allow more


@dataclass
class _PolicyCache:
    """Module-level lazily-loaded policy cache.

    The ConfigMap is mounted on the worker pod; reading it once on first
    use is cheaper than re-reading every send. Bump the Deployment
    annotation to force re-roll if you push a hot policy change.
    """

    policies: dict[str, InstancePolicy] = field(default_factory=dict)
    loaded: bool = False
    source_path: Path | None = None


_POLICY_CACHE = _PolicyCache()


# ---------------------------------------------------------------------------
# Configuration loaders
# ---------------------------------------------------------------------------


CONFIGMAP_PATH = Path(
    os.environ.get("SELVA_MASTODON_POLICIES_PATH", "/etc/selva/mastodon_policies.yaml")
)


# Persona-id sanitisation — matches the rule called out in the module
# docstring: upper-case, replace non-alphanumerics with underscores.
_PERSONA_SANITISE_RE = re.compile(r"[^A-Z0-9]+")


def _persona_env_suffix(persona_id: str) -> str:
    """Map a persona id to its access-token env var suffix.

    ``"growth-bot-1"``  → ``"GROWTH_BOT_1"``
    ``"default"``       → ``"DEFAULT"``
    ``"a.b/c"``         → ``"A_B_C"``
    """
    return _PERSONA_SANITISE_RE.sub("_", persona_id.upper()).strip("_") or "DEFAULT"


def _required_env(persona_id: str) -> dict[str, str]:
    """Return the dict of required Mastodon env vars, raising
    ToolNotConfiguredError when any is missing.

    NEVER returns a partially-populated dict — the operator must
    provision the instance URL AND the per-persona access token
    together. Returns ``{"instance_url": ..., "access_token": ...}``.
    """
    instance_url = os.environ.get("MASTODON_INSTANCE_URL", "").strip()
    suffix = _persona_env_suffix(persona_id)
    token_var = f"MASTODON_ACCESS_TOKEN_{suffix}"
    access_token = os.environ.get(token_var, "").strip()

    missing: list[str] = []
    if not instance_url:
        missing.append("MASTODON_INSTANCE_URL")
    if not access_token:
        missing.append(token_var)
    if missing:
        raise ToolNotConfiguredError(
            "Mastodon credentials missing — operator must provision env vars: "
            + ", ".join(missing)
        )
    return {"instance_url": instance_url, "access_token": access_token}


def _normalise_instance(value: str) -> str:
    """Return the canonical instance host (no scheme, no trailing slash,
    lowercased). ``"https://mastodon.social/"`` → ``"mastodon.social"``.
    """
    v = value.strip().lower()
    v = v.removeprefix("https://").removeprefix("http://")
    return v.rstrip("/")


def _load_policies(path: Path | None = None) -> dict[str, InstancePolicy]:
    """Load + cache the per-instance policy ConfigMap.

    Returns an empty dict when the ConfigMap is absent (fallback path:
    every instance treated with conservative defaults).

    ``path`` defaults to the module-level :data:`CONFIGMAP_PATH`. The
    indirection (rather than ``path: Path = CONFIGMAP_PATH``) is so
    test code can ``monkeypatch.setattr(mastodon_tools, 'CONFIGMAP_PATH',
    other_path)`` and have it take effect — function-default
    expressions are bound at function-def time and ignore later
    monkeypatching.
    """
    if path is None:
        path = CONFIGMAP_PATH

    if _POLICY_CACHE.loaded and _POLICY_CACHE.source_path == path:
        return _POLICY_CACHE.policies

    policies: dict[str, InstancePolicy] = {}
    if path.exists():
        try:
            import yaml  # late import — yaml is a dep elsewhere

            raw = yaml.safe_load(path.read_text()) or {}
            for entry in raw.get("policies", []):
                inst = _normalise_instance(entry.get("instance") or "")
                if not inst:
                    continue
                allowed_raw = entry.get("allowed_visibilities") or list(
                    _DEFAULT_ALLOWED_VISIBILITIES
                )
                allowed = tuple(
                    v for v in allowed_raw if v in _VALID_VISIBILITIES
                ) or _DEFAULT_ALLOWED_VISIBILITIES
                rate_minutes = int(
                    entry.get("rate_limit_minutes", _DEFAULT_RATE_LIMIT_MINUTES)
                )
                policies[inst] = InstancePolicy(
                    instance=inst,
                    disclosure_required=bool(entry.get("disclosure_required", True)),
                    allowed_visibilities=allowed,
                    rate_limit_minutes=max(1, rate_minutes),
                    cw_required=bool(entry.get("cw_required", False)),
                    max_chars=int(entry.get("max_chars", 500)),
                )
        except Exception as exc:
            logger.warning(
                "mastodon_policies.yaml load failed (%s) — falling back to safe defaults",
                exc,
            )

    _POLICY_CACHE.policies = policies
    _POLICY_CACHE.loaded = True
    _POLICY_CACHE.source_path = path
    return policies


def _resolve_policy(instance: str) -> InstancePolicy:
    """Return the loaded policy for ``instance``, defaulting to
    conservative-everything when the instance is not listed."""
    key = _normalise_instance(instance)
    policies = _load_policies()
    if key in policies:
        return policies[key]
    return InstancePolicy(instance=key)


# ---------------------------------------------------------------------------
# Disclosure footer
# ---------------------------------------------------------------------------


_DISCLOSURE_FOOTER = (
    "\n\n---\n"
    "*Posted by an AI agent on behalf of MADFAM. "
    "https://madfam.io/ai-disclosure*"
)


def _maybe_apply_disclosure(body: str, policy: InstancePolicy) -> tuple[str, bool]:
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


async def _check_and_set_rate_limit(instance: str, ttl_seconds: int) -> None:
    """Reject (raise RuntimeError) when the same instance was posted
    to within the last ``ttl_seconds``. SETs the Redis key on success.

    Behaviour when Redis is unavailable: log + allow. The HITL gate +
    LLM-tier throttling already provide a soft brake; failing closed
    on Redis outage would block legitimate ops.
    """
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        logger.debug(
            "REDIS_URL unset — skipping mastodon rate-limit (HITL still gates)"
        )
        return

    key = f"selva:mastodon:last_post:{_normalise_instance(instance)}"
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url)
        try:
            existing = await r.get(key)
            if existing is not None:
                ttl = await r.ttl(key)
                raise RuntimeError(
                    f"Mastodon rate-limit hit for {instance}: another post "
                    f"was made recently (resets in ~{max(0, ttl)}s)"
                )
            # SETEX with NX semantics — atomic claim of the slot.
            await r.set(key, "1", ex=ttl_seconds, nx=True)
        finally:
            with contextlib.suppress(Exception):
                await r.aclose()
    except RuntimeError:
        raise
    except Exception as exc:
        logger.warning("Mastodon rate-limit check failed (%s) — allowing post", exc)


# ---------------------------------------------------------------------------
# Mastodon.py glue (kept thin for testability)
# ---------------------------------------------------------------------------


def _build_mastodon_client(creds: dict[str, str]) -> Any:
    """Return a Mastodon.py instance.

    Late-imports Mastodon.py so the module loads in environments without
    it (CI test discovery, etc.). When the lib is missing we raise
    :class:`ToolNotConfiguredError` so ops gets a clear signal.
    """
    try:
        from mastodon import Mastodon  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ToolNotConfiguredError(
            "Mastodon.py not installed — `pip install Mastodon.py>=1.8` "
            "in the worker image"
        ) from exc

    return Mastodon(
        access_token=creds["access_token"],
        api_base_url=creds["instance_url"],
    )


def _submit_via_mastodon(
    client: Any,
    *,
    status: str,
    visibility: str,
    spoiler_text: str | None,
    sensitive: bool,
) -> dict[str, str]:
    """Synchronous Mastodon.py submission. Mastodon.py does not have an
    async API, so callers should run this in a threadpool when the
    surrounding handler is async.

    Returns ``{"post_url": permalink, "post_id": status_id}``.
    """
    submission = client.status_post(
        status=status,
        visibility=visibility,
        spoiler_text=spoiler_text or None,
        sensitive=sensitive,
    )
    # Mastodon.py returns an AttrDict (dict-like) with `id` and `url`.
    return {
        "post_url": str(submission["url"]),
        "post_id": str(submission["id"]),
    }


# ---------------------------------------------------------------------------
# PostHog event emission
# ---------------------------------------------------------------------------


def _emit_outbound_post_event(
    instance: str,
    persona_id: str,
    post_id: str,
    disclosure_applied: bool,
    visibility: str,
) -> None:
    """Fire the ``outbound_post.created`` PostHog event. Fire-and-forget."""
    try:
        from nexus_api.analytics import track

        track(
            persona_id or "anonymous",
            "outbound_post.created",
            {
                "instance": instance,
                "persona_id": persona_id,
                "post_id": post_id,
                "platform": "mastodon",
                "disclosure_applied": disclosure_applied,
                "visibility": visibility,
            },
        )
    except Exception:
        logger.debug("PostHog track failed for outbound_post.created", exc_info=True)


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class MastodonPostTool(BaseTool):
    """Submit a status (toot) to a Mastodon instance via Mastodon.py,
    applying the operator-configured disclosure + rate-limit + visibility
    policy.

    Returns ``ToolResult(data={"post_url": ..., "post_id": ...})``.
    """

    name = "mastodon_post"
    description = (
        "Submit a status (toot) to a Mastodon instance. Mandatory AI-agent "
        "disclosure is appended automatically when the per-instance policy "
        "requires it (default: always). Default visibility is 'unlisted' to "
        "avoid spamming public timelines; per-instance policy can pin it "
        "stricter. Rate-limited to 1 post per instance per 30 minutes "
        "(per-instance override possible). Requires MASTODON_INSTANCE_URL "
        "and MASTODON_ACCESS_TOKEN_<persona_id> env vars; raises "
        "ToolNotConfiguredError when missing. Returns the post permalink + id."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "instance": {
                    "type": "string",
                    "description": (
                        "Target Mastodon instance host (e.g. "
                        "'mastodon.social', 'fosstodon.org'). Used for "
                        "policy lookup + rate-limiting; the actual POST "
                        "goes to MASTODON_INSTANCE_URL."
                    ),
                },
                "status": {
                    "type": "string",
                    "description": (
                        "Status text (markdown is NOT rendered by "
                        "Mastodon — plain text + URLs only). Disclosure "
                        "footer auto-appended when policy requires."
                    ),
                    "maxLength": 5000,
                },
                "visibility": {
                    "type": "string",
                    "enum": ["public", "unlisted", "private", "direct"],
                    "description": (
                        "Status visibility. Default 'unlisted' — accessible "
                        "by URL but absent from public timelines. Per-instance "
                        "policy may bound the allow-list further."
                    ),
                    "default": "unlisted",
                },
                "persona_id": {
                    "type": "string",
                    "description": (
                        "Selva persona id; selects the per-persona access "
                        "token env var (MASTODON_ACCESS_TOKEN_<persona_id>) "
                        "AND tags the PostHog attribution."
                    ),
                    "default": "default",
                },
                "content_warning": {
                    "type": ["string", "null"],
                    "description": (
                        "Optional content warning (Mastodon spoiler_text). "
                        "Required when per-instance policy sets cw_required=true."
                    ),
                },
                "sensitive": {
                    "type": "boolean",
                    "description": (
                        "Mark media + body as sensitive (NSFW affordance "
                        "in clients). Defaults to false."
                    ),
                    "default": False,
                },
            },
            "required": ["instance", "status"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        instance_raw = (kwargs.get("instance") or "").strip()
        status = kwargs.get("status") or ""
        visibility_req = (kwargs.get("visibility") or "unlisted").strip().lower()
        persona_id = kwargs.get("persona_id") or "default"
        content_warning = kwargs.get("content_warning")
        sensitive = bool(kwargs.get("sensitive") or False)

        if not instance_raw:
            return ToolResult(success=False, error="instance is required")
        if not status:
            return ToolResult(success=False, error="status is required")
        if visibility_req not in _VALID_VISIBILITIES:
            return ToolResult(
                success=False,
                error=(
                    f"invalid visibility '{visibility_req}'; must be one of "
                    f"{sorted(_VALID_VISIBILITIES)}"
                ),
            )

        instance = _normalise_instance(instance_raw)

        # Resolve policy + apply disclosure BEFORE checking creds, so a
        # mis-configured operator still sees the policy violation in the
        # audit trail when they do hook up creds.
        policy = _resolve_policy(instance)

        # Visibility allow-list per instance policy.
        if visibility_req not in policy.allowed_visibilities:
            return ToolResult(
                success=False,
                error=(
                    f"Mastodon policy for {instance} forbids visibility "
                    f"'{visibility_req}'; allowed: "
                    f"{list(policy.allowed_visibilities)}"
                ),
            )

        # CW gate per instance policy.
        if policy.cw_required and not (content_warning and content_warning.strip()):
            return ToolResult(
                success=False,
                error=(
                    f"Mastodon policy for {instance} requires a content "
                    "warning (content_warning argument)"
                ),
            )

        body_to_send, disclosure_applied = _maybe_apply_disclosure(status, policy)

        # Length check post-disclosure (footer adds ~75 chars).
        if len(body_to_send) > policy.max_chars:
            return ToolResult(
                success=False,
                error=(
                    f"status length {len(body_to_send)} exceeds "
                    f"per-instance max_chars {policy.max_chars} "
                    "(disclosure footer accounts for ~75 chars)"
                ),
            )

        # Credential check — raises ToolNotConfiguredError on miss.
        # Never returns placeholder output.
        creds = _required_env(persona_id)

        # Rate-limit (Redis-backed). Raises RuntimeError on hit.
        try:
            await _check_and_set_rate_limit(
                instance, ttl_seconds=policy.rate_limit_minutes * 60
            )
        except RuntimeError as exc:
            return ToolResult(success=False, error=str(exc))

        # Submit via Mastodon.py in a threadpool — Mastodon.py is sync.
        try:
            import asyncio

            client = _build_mastodon_client(creds)
            result = await asyncio.to_thread(
                _submit_via_mastodon,
                client,
                status=body_to_send,
                visibility=visibility_req,
                spoiler_text=content_warning,
                sensitive=sensitive,
            )
        except ToolNotConfiguredError:
            raise
        except Exception as exc:
            logger.exception("Mastodon submit failed for %s", instance)
            return ToolResult(
                success=False,
                error=f"Mastodon submit failed: {exc.__class__.__name__}: {exc}",
            )

        post_id = result["post_id"]
        post_url = result["post_url"]

        _emit_outbound_post_event(
            instance=instance,
            persona_id=persona_id,
            post_id=post_id,
            disclosure_applied=disclosure_applied,
            visibility=visibility_req,
        )

        logger.info(
            "Mastodon post submitted: %s persona=%s post_id=%s "
            "visibility=%s disclosure=%s",
            instance,
            persona_id,
            post_id,
            visibility_req,
            disclosure_applied,
        )

        return ToolResult(
            success=True,
            output=post_url,
            data={
                "post_url": post_url,
                "post_id": post_id,
                "instance": instance,
                "visibility": visibility_req,
                "disclosure_applied": disclosure_applied,
                "persona_id": persona_id,
            },
        )


# Tools are TENANT audience (default) — every tenant swarm can run the
# Mastodon promo playbook so long as the operator has provisioned a
# per-persona access token. Platform-only Mastodon ops would be a
# separate tool.
__all__ = [
    "InstancePolicy",
    "MastodonPolicyError",
    "MastodonPostTool",
    "ToolNotConfiguredError",
]
