"""GitHub admin tools (RFC 0006 Sprint 1).

Implements the ``github_admin.*`` tool family described in
``internal-devops/rfcs/0006-selva-github-admin-tools.md``. Four tools
ship in this sprint:

- ``github_admin.create_team`` -- idempotent on ``(org, team_slug)``:
  returns the existing team if the slug already exists, creates a new
  team otherwise.
- ``github_admin.set_team_membership`` -- reconciles the desired member
  list with the live list. Add-only is ALLOW; removals are ASK.
- ``github_admin.set_branch_protection`` -- applies a branch-protection
  rule on ``org/repo@branch``. First-time application is ASK_DUAL, mod-
  ifications are ASK.
- ``github_admin.audit_team_membership`` -- read-only; returns the live
  member list plus a drift diff against the most recent ``set_team_
  membership`` audit row. ALLOW everywhere.

Transport is direct ``httpx`` against the GitHub REST API. We deliberately
don't pull in PyGithub: httpx is already a transitive dep, the API
surface we use is tiny (5 endpoints), and a bare client gives us precise
control over timeouts and error sanitisation. Revisit if the tool grows.

The GitHub PAT is read from a K8s Secret named ``selva-github-admin-token``
via ``GITHUB_ADMIN_PAT_PATH`` env var (projected SA volume) or the
``GITHUB_ADMIN_PAT`` env var fallback for local dev. The PAT is NEVER
logged, returned, or written to the audit row -- only its 8-hex SHA-256
prefix is persisted (for rotation correlation).

What this tool deliberately does NOT do (deferred to later sprints):

- **Delete teams / repos**. Team deletion rewrites historical review
  records; route through operator UI. RFC 0006 §"Tools deliberately NOT
  offered".
- **Rotate / revoke the PAT**. Rotation is Sprint 2, coordinated with
  RFC 0005's rotation primitive.
- **Multi-org support**. v0.1 scopes to ``ALLOWED_ORGS`` (currently
  just ``madfam-org``). Adding a second org requires a manifest PR.
- **Raw API passthrough**. Only structured tools; no escape hatch.
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

logger = logging.getLogger("selva.tools.github_admin")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Allow-list of orgs the tool is permitted to touch. Any org not in this
# set is rejected pre-API so a confused agent can't accidentally walk
# into a different org. Extending this list requires both a code PR and
# a PAT with the new org's ``admin:org`` scope.
ALLOWED_ORGS = frozenset({"madfam-org"})

# Team privacy values per GitHub API -- "closed" = visible to org
# members, "secret" = only visible to members + owners. "open" does not
# exist in the API (historical alias removed in 2023).
ALLOWED_PRIVACY = frozenset({"closed", "secret"})

# Team roles per the /orgs/{org}/teams/{team}/memberships/{user} API.
ALLOWED_MEMBERSHIP_ROLES = frozenset({"member", "maintainer"})

# Filesystem mount for the PAT when the tool runs inside the cluster.
# The secret-reader helper in secret_reader.py prefers this path; the
# env var is only consulted as a fallback (local dev, CI).
GITHUB_ADMIN_PAT_PATH_DEFAULT = "/var/run/secrets/selva-github-admin-token/token"

# GitHub API base. Parameterised so tests can point at a mock server.
GITHUB_API_BASE = os.environ.get("GITHUB_API_BASE", "https://api.github.com")

# Per-call HTTP timeout. GitHub is generally fast; if a call takes >15s
# something is wrong, fail fast so the HITL queue doesn't stack up.
HTTP_TIMEOUT_SECONDS = 15.0


class GithubAdminOperation(StrEnum):
    """Operation taxonomy -- must match the CHECK constraint in migration 0020."""

    CREATE_TEAM = "create_team"
    SET_TEAM_MEMBERSHIP = "set_team_membership"
    SET_BRANCH_PROTECTION = "set_branch_protection"
    AUDIT_TEAM_MEMBERSHIP = "audit_team_membership"


# ---------------------------------------------------------------------------
# Helpers (pure -- no network, no DB)
# ---------------------------------------------------------------------------


def _sha256_full(value: str) -> str:
    """SHA-256 hex digest of the value. Never returned to callers."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def token_sha256_prefix(token: str) -> str:
    """First 8 hex chars of SHA-256(token). Safe to log and return."""
    return _sha256_full(token)[:8]


def _read_github_pat() -> str | None:
    """Read the GitHub admin PAT from the mounted K8s secret, or env fallback.

    Returns ``None`` if neither source is available -- callers must
    surface a missing-secret error to the operator. The PAT NEVER leaves
    this module in raw form; only the prefix is ever exposed.
    """
    pat_path = os.environ.get("GITHUB_ADMIN_PAT_PATH", GITHUB_ADMIN_PAT_PATH_DEFAULT)
    if os.path.exists(pat_path):
        try:
            with open(pat_path, encoding="utf-8") as fp:
                token = fp.read().strip()
                if token:
                    return token
        except OSError:
            logger.warning("github_admin PAT path exists but unreadable: %s", pat_path)
    env_token = os.environ.get("GITHUB_ADMIN_PAT")
    if env_token:
        return env_token.strip()
    return None


def _validate_org(org: str) -> str | None:
    """Return an error message if ``org`` isn't allow-listed, else None."""
    if org not in ALLOWED_ORGS:
        return (
            f"org {org!r} is not in the allow-list {sorted(ALLOWED_ORGS)}. "
            "Extending this list requires a code PR + PAT with the new "
            "org's admin:org scope."
        )
    return None


def _validate_slug(slug: str, *, field: str) -> str | None:
    """Basic sanity check on GitHub slugs/usernames -- 1..39 chars, no spaces."""
    if not slug or not isinstance(slug, str):
        return f"{field} is required"
    if len(slug) > 39:
        return f"{field} exceeds max length (39 chars)"
    if " " in slug or "\n" in slug or "\t" in slug:
        return f"{field} must not contain whitespace"
    return None


# ---------------------------------------------------------------------------
# HITL resolution
# ---------------------------------------------------------------------------


def _resolve_hitl_level(operation: GithubAdminOperation, *, removing: bool) -> str:
    """Return the HITL level string for an operation.

    Per RFC 0006 §"HITL gates per operation":

    - ``create_team``: ASK
    - ``set_team_membership`` (add-only): ALLOW
    - ``set_team_membership`` with removals: ASK
    - ``set_branch_protection`` first-time: ASK_DUAL (signalled by caller
      via ``first_time=True``; we treat every call as ASK_DUAL here for
      Sprint 1 conservative default -- see "RFC gaps" in PR body)
    - ``audit_team_membership``: ALLOW
    """
    try:
        from selva_permissions.engine import PermissionEngine
        from selva_permissions.types import (
            ActionCategory,
            PermissionLevel,
        )
    except Exception:  # pragma: no cover
        # Permissions package unavailable -> fail closed.
        if operation == GithubAdminOperation.AUDIT_TEAM_MEMBERSHIP:
            return "allow"
        return "ask"

    if operation == GithubAdminOperation.AUDIT_TEAM_MEMBERSHIP:
        level = PermissionLevel.ALLOW
    elif operation == GithubAdminOperation.CREATE_TEAM:
        level = PermissionLevel.ASK
    elif operation == GithubAdminOperation.SET_TEAM_MEMBERSHIP:
        level = PermissionLevel.ASK if removing else PermissionLevel.ALLOW
    elif operation == GithubAdminOperation.SET_BRANCH_PROTECTION:
        # Conservative default: every branch-protection mutation is
        # ASK_DUAL in Sprint 1. Sprint 2 will distinguish first-time
        # from modify via an audit lookup.
        level = PermissionLevel.ASK_DUAL
    else:  # pragma: no cover — defensive
        level = PermissionLevel.ASK

    engine = PermissionEngine(overrides={ActionCategory.GITHUB_ADMIN: level})
    result = engine.evaluate(ActionCategory.GITHUB_ADMIN)
    return result.level.value


# ---------------------------------------------------------------------------
# GitHub REST API thin wrapper
# ---------------------------------------------------------------------------


class _GithubApiError(Exception):
    """Surfaced when the GitHub API returns an unrecoverable error.

    Callers MUST scrub any echoed URL or headers from the message before
    raising -- GitHub occasionally reflects request bits back in errors.
    """


def _build_client(token: str) -> httpx.Client:
    """Build an httpx client with GitHub auth + sane defaults."""
    return httpx.Client(
        base_url=GITHUB_API_BASE,
        timeout=HTTP_TIMEOUT_SECONDS,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "selva-github-admin/0.1",
        },
    )


def _gh_raise_for_status(resp: httpx.Response) -> None:
    """Raise ``_GithubApiError`` on non-2xx, scrubbed of request body."""
    if resp.is_success:
        return
    # Intentionally do not include resp.text -- GitHub error bodies can
    # echo submitted usernames or rule values, which we don't want in
    # the scrubbed path.
    raise _GithubApiError(
        f"github api error status={resp.status_code} "
        f"method={resp.request.method} url_path={resp.url.path}"
    )


def _get_team(client: httpx.Client, org: str, team_slug: str) -> dict[str, Any] | None:
    """GET /orgs/{org}/teams/{team_slug}. 404 -> None."""
    resp = client.get(f"/orgs/{org}/teams/{team_slug}")
    if resp.status_code == 404:
        return None
    _gh_raise_for_status(resp)
    return resp.json()


def _create_team(
    client: httpx.Client,
    org: str,
    *,
    team_name: str,
    description: str,
    privacy: str,
    parent_team_id: int | None,
) -> dict[str, Any]:
    """POST /orgs/{org}/teams."""
    payload: dict[str, Any] = {
        "name": team_name,
        "description": description,
        "privacy": privacy,
    }
    if parent_team_id is not None:
        payload["parent_team_id"] = parent_team_id
    resp = client.post(f"/orgs/{org}/teams", json=payload)
    _gh_raise_for_status(resp)
    return resp.json()


def _list_team_members(client: httpx.Client, org: str, team_slug: str) -> list[dict[str, Any]]:
    """GET /orgs/{org}/teams/{team_slug}/members with role classification.

    Paginated -- iterates ``per_page=100``. For v0.1 we assume teams
    under 500 members (safe: org is ~20 people). Hard cap at 1000.
    """
    members: list[dict[str, Any]] = []
    for role in ("member", "maintainer"):
        page = 1
        while True:
            resp = client.get(
                f"/orgs/{org}/teams/{team_slug}/members",
                params={"role": role, "per_page": 100, "page": page},
            )
            if resp.status_code == 404:
                return []
            _gh_raise_for_status(resp)
            batch = resp.json()
            for entry in batch:
                members.append({"login": entry["login"], "role": role})
            if len(batch) < 100:
                break
            page += 1
            if page > 10:  # hard cap -- see docstring
                logger.warning(
                    "team_members pagination cap hit org=%s team=%s",
                    org,
                    team_slug,
                )
                break
    return members


def _set_team_membership(
    client: httpx.Client,
    org: str,
    team_slug: str,
    *,
    username: str,
    role: str,
) -> None:
    """PUT /orgs/{org}/teams/{team_slug}/memberships/{username}."""
    resp = client.put(
        f"/orgs/{org}/teams/{team_slug}/memberships/{username}",
        json={"role": role},
    )
    _gh_raise_for_status(resp)


def _remove_team_membership(
    client: httpx.Client, org: str, team_slug: str, *, username: str
) -> None:
    """DELETE /orgs/{org}/teams/{team_slug}/memberships/{username}."""
    resp = client.delete(f"/orgs/{org}/teams/{team_slug}/memberships/{username}")
    # 404 on remove is fine -- user wasn't a member anyway.
    if resp.status_code == 404:
        return
    _gh_raise_for_status(resp)


def _set_branch_protection(
    client: httpx.Client,
    org: str,
    repo: str,
    branch: str,
    *,
    rules: dict[str, Any],
) -> dict[str, Any]:
    """PUT /repos/{org}/{repo}/branches/{branch}/protection.

    The payload shape is driven by GitHub's API:
      https://docs.github.com/en/rest/branches/branch-protection
    Caller builds the ``rules`` dict; we don't reshape it.
    """
    resp = client.put(
        f"/repos/{org}/{repo}/branches/{branch}/protection",
        json=rules,
    )
    _gh_raise_for_status(resp)
    return resp.json()


# ---------------------------------------------------------------------------
# Audit shim -- lazy import so tests can stub it
# ---------------------------------------------------------------------------


def _audit_record(
    *,
    approval_request_id: str,
    agent_id: str | None,
    actor_user_sub: str | None,
    operation: str,
    target_org: str,
    target_repo: str | None,
    target_team_slug: str | None,
    target_branch: str | None,
    token_prefix: str,
    request_body: dict[str, Any],
    response_summary: dict[str, Any],
    rationale: str,
    status: str,
    error_message: str | None,
    request_id: str | None,
) -> None:
    """Append a row to ``github_admin_audit_log``. Never raises.

    Lazy import so test code can stub this out without needing the
    nexus-api package on the path.
    """
    try:
        from nexus_api.audit.github_admin_audit import (
            append_audit_row,
        )
    except Exception:  # pragma: no cover — missing dep is dev-only
        logger.debug("nexus_api.audit.github_admin_audit unavailable; skipping DB write")
        return
    try:
        append_audit_row(
            approval_request_id=approval_request_id,
            agent_id=agent_id,
            actor_user_sub=actor_user_sub,
            operation=operation,
            target_org=target_org,
            target_repo=target_repo,
            target_team_slug=target_team_slug,
            target_branch=target_branch,
            token_sha256_prefix=token_prefix,
            request_body=request_body,
            response_summary=response_summary,
            rationale=rationale,
            request_id=request_id,
            status=status,
            error_message=error_message,
        )
    except Exception:  # noqa: BLE001 — audit failures MUST NOT block the tool
        logger.error(
            "github_admin audit append failed (no PAT content in log)",
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Common entry-point logic
# ---------------------------------------------------------------------------


def _scrub_request_body(body: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``body`` with any sensitive-looking keys redacted.

    Defense in depth -- the contract is that ``request_body`` is always
    safe to log because the tool never accepts PATs as arguments. But if
    a future caller slips a ``token`` / ``password`` / ``secret`` field
    in, we redact at the audit boundary.
    """
    sensitive_keys = {
        "token",
        "password",
        "secret",
        "pat",
        "api_key",
        "authorization",
    }
    redacted: dict[str, Any] = {}
    for k, v in body.items():
        if k.lower() in sensitive_keys and isinstance(v, str):
            redacted[k] = f"redacted:sha256:{_sha256_full(v)[:8]}"
        else:
            redacted[k] = v
    return redacted


def _missing_pat_result(approval_request_id: str, operation: str) -> ToolResult:
    """Consistent missing-PAT error surface -- no value content."""
    return ToolResult(
        success=False,
        error=(
            "github admin PAT not available: expected K8s secret "
            "'selva-github-admin-token' mounted at "
            f"{GITHUB_ADMIN_PAT_PATH_DEFAULT} or env var GITHUB_ADMIN_PAT. "
            "Operator provisions this out-of-band per RFC 0006 §'Approval "
            "checkpoints'."
        ),
        data={
            "approval_request_id": approval_request_id,
            "status": "failed",
            "operation": operation,
        },
    )


# ---------------------------------------------------------------------------
# Tool: create_team
# ---------------------------------------------------------------------------


class GithubAdminCreateTeamTool(BaseTool):
    """``github_admin.create_team`` -- RFC 0006 Sprint 1.

    Idempotent on ``(org, team_slug)``. If a team with that slug already
    exists, the tool returns the existing team's metadata with
    ``status="already_exists"`` and does not call the create endpoint.
    Otherwise ASK-gated: returns ``pending_approval`` until the operator
    confirms via the /office queue.

    Parameters
    ----------
    org : str
        Target org -- must be in ``ALLOWED_ORGS``.
    team_slug : str
        GitHub slug -- lowercase, hyphen-separated, <=39 chars.
    team_name : str
        Human-readable name (shown in GitHub UI).
    description : str
        Short description of the team's purpose.
    privacy : "closed" | "secret"
        Team visibility. Default "closed".
    parent_team_id : int, optional
        Nested teams.
    rationale : str
        Human-readable reason (>=10 chars).
    """

    name = "github_admin_create_team"
    description = (
        "Create a GitHub team in the allow-listed org. Idempotent on slug: "
        "returns the existing team if the slug matches. Gated by the "
        "GITHUB_ADMIN action category (ASK)."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "org": {
                    "type": "string",
                    "enum": sorted(ALLOWED_ORGS),
                    "description": "Target org (must be allow-listed).",
                },
                "team_slug": {
                    "type": "string",
                    "description": "GitHub team slug (e.g. 'platform').",
                },
                "team_name": {
                    "type": "string",
                    "description": "Display name (e.g. 'Platform').",
                },
                "description": {
                    "type": "string",
                    "description": "Short description of the team's purpose.",
                },
                "privacy": {
                    "type": "string",
                    "enum": sorted(ALLOWED_PRIVACY),
                    "description": "Visibility; default 'closed'.",
                },
                "parent_team_id": {
                    "type": "integer",
                    "description": "Optional parent team ID for nesting.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Human-readable reason for creation.",
                },
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["org", "team_slug", "team_name", "description", "rationale"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        org = str(kwargs.get("org") or "")
        team_slug = str(kwargs.get("team_slug") or "")
        team_name = str(kwargs.get("team_name") or "")
        description = str(kwargs.get("description") or "")
        privacy = str(kwargs.get("privacy") or "closed")
        parent_team_id = kwargs.get("parent_team_id")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        approval_request_id = str(uuid.uuid4())
        operation = GithubAdminOperation.CREATE_TEAM.value

        # --- validation ---
        if err := _validate_org(org):
            return ToolResult(success=False, error=err)
        if err := _validate_slug(team_slug, field="team_slug"):
            return ToolResult(success=False, error=err)
        if not team_name:
            return ToolResult(success=False, error="team_name is required")
        if privacy not in ALLOWED_PRIVACY:
            return ToolResult(
                success=False,
                error=f"privacy must be one of {sorted(ALLOWED_PRIVACY)}",
            )
        if not rationale or len(rationale) < 10:
            return ToolResult(
                success=False,
                error="rationale is required (>=10 chars)",
            )

        # --- PAT lookup ---
        pat = _read_github_pat()
        if pat is None:
            return _missing_pat_result(approval_request_id, operation)
        token_prefix = token_sha256_prefix(pat)

        request_body = _scrub_request_body(
            {
                "org": org,
                "team_slug": team_slug,
                "team_name": team_name,
                "description": description,
                "privacy": privacy,
                "parent_team_id": parent_team_id,
                "rationale": rationale,
            }
        )

        logger.info(
            "github_admin create_team requested org=%s slug=%s token_prefix=%s approval_id=%s",
            org,
            team_slug,
            token_prefix,
            approval_request_id,
        )

        # --- idempotency check: look up the team by slug ---
        try:
            with _build_client(pat) as client:
                existing = _get_team(client, org, team_slug)
        except _GithubApiError as exc:
            msg = str(exc)
            logger.error("github_admin create_team lookup failed: %s", msg)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary={},
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(success=False, error=f"github api error: {msg}")

        if existing is not None:
            logger.info(
                "github_admin create_team idempotent hit org=%s slug=%s",
                org,
                team_slug,
            )
            response_summary = {
                "team_id": existing.get("id"),
                "team_slug": existing.get("slug"),
                "already_existed": True,
            }
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary=response_summary,
                rationale=rationale,
                status="applied",  # no-op is still a successful outcome
                error_message=None,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(
                output=(
                    f"Team {org}/{team_slug} already exists "
                    f"(id={existing.get('id')}); no action taken."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "already_exists",
                    "team_id": existing.get("id"),
                    "team_slug": existing.get("slug"),
                    "hitl_level": "allow",
                    "token_sha256_prefix": token_prefix,
                    "operation": operation,
                },
            )

        # --- HITL gate (ASK) ---
        hitl_level = _resolve_hitl_level(GithubAdminOperation.CREATE_TEAM, removing=False)
        if hitl_level in ("ask", "ask_dual"):
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary={},
                rationale=rationale,
                status="pending_approval",
                error_message=None,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(
                output=(
                    f"Team creation for {org}/{team_slug} is pending {hitl_level} "
                    f"approval (token_prefix={token_prefix})."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "token_sha256_prefix": token_prefix,
                    "operation": operation,
                },
            )

        # --- ALLOW path: execute the create now ---
        try:
            with _build_client(pat) as client:
                created = _create_team(
                    client,
                    org,
                    team_name=team_name,
                    description=description,
                    privacy=privacy,
                    parent_team_id=(int(parent_team_id) if parent_team_id is not None else None),
                )
        except _GithubApiError as exc:
            msg = str(exc)
            logger.error(
                "github_admin create_team api failed org=%s slug=%s err=%s",
                org,
                team_slug,
                msg,
            )
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary={},
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(success=False, error=f"github api error: {msg}")

        response_summary = {
            "team_id": created.get("id"),
            "team_slug": created.get("slug"),
            "already_existed": False,
        }
        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            operation=operation,
            target_org=org,
            target_repo=None,
            target_team_slug=team_slug,
            target_branch=None,
            token_prefix=token_prefix,
            request_body=request_body,
            response_summary=response_summary,
            rationale=rationale,
            status="applied",
            error_message=None,
            request_id=request_id if isinstance(request_id, str) else None,
        )
        return ToolResult(
            output=(
                f"Team {org}/{team_slug} created "
                f"(id={created.get('id')}, token_prefix={token_prefix})."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "team_id": created.get("id"),
                "team_slug": created.get("slug"),
                "hitl_level": hitl_level,
                "token_sha256_prefix": token_prefix,
                "operation": operation,
            },
        )


# ---------------------------------------------------------------------------
# Tool: set_team_membership
# ---------------------------------------------------------------------------


class GithubAdminSetTeamMembershipTool(BaseTool):
    """``github_admin.set_team_membership`` -- RFC 0006 Sprint 1.

    Reconciles the desired member list with the live list. Computes a
    diff (add / remove / unchanged) and applies it via PUT/DELETE
    calls. Add-only is ALLOW; any removal escalates to ASK.

    Parameters
    ----------
    org : str
    team_slug : str
    members : list[str]
        Desired GitHub usernames; role applied uniformly.
    role : "member" | "maintainer"
        Default "member".
    removed_members : list[str], optional
        Explicit removals -- the tool does NOT auto-prune members
        missing from ``members``. This mirrors RFC 0006's "removed_
        members" opt-in for defense against accidental prune.
    rationale : str
    """

    name = "github_admin_set_team_membership"
    description = (
        "Reconcile GitHub team membership. Emits a diff of adds / removes. "
        "Gated ALLOW for add-only, ASK for any removal."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "org": {
                    "type": "string",
                    "enum": sorted(ALLOWED_ORGS),
                },
                "team_slug": {"type": "string"},
                "members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Desired GitHub usernames (role applied uniformly).",
                },
                "role": {
                    "type": "string",
                    "enum": sorted(ALLOWED_MEMBERSHIP_ROLES),
                    "description": "Membership role; default 'member'.",
                },
                "removed_members": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit removals (opt-in, never auto-pruned).",
                },
                "rationale": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["org", "team_slug", "members", "rationale"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        org = str(kwargs.get("org") or "")
        team_slug = str(kwargs.get("team_slug") or "")
        members_raw = kwargs.get("members") or []
        removed_raw = kwargs.get("removed_members") or []
        role = str(kwargs.get("role") or "member")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        approval_request_id = str(uuid.uuid4())
        operation = GithubAdminOperation.SET_TEAM_MEMBERSHIP.value

        # --- validation ---
        if err := _validate_org(org):
            return ToolResult(success=False, error=err)
        if err := _validate_slug(team_slug, field="team_slug"):
            return ToolResult(success=False, error=err)
        if not isinstance(members_raw, list):
            return ToolResult(success=False, error="members must be a list of GitHub usernames")
        if not isinstance(removed_raw, list):
            return ToolResult(
                success=False,
                error="removed_members must be a list (or omitted)",
            )
        if role not in ALLOWED_MEMBERSHIP_ROLES:
            return ToolResult(
                success=False,
                error=f"role must be one of {sorted(ALLOWED_MEMBERSHIP_ROLES)}",
            )
        if not rationale or len(rationale) < 10:
            return ToolResult(success=False, error="rationale is required (>=10 chars)")

        members = [str(m).strip() for m in members_raw if str(m).strip()]
        removed = [str(m).strip() for m in removed_raw if str(m).strip()]
        for m in members + removed:
            if err := _validate_slug(m, field="member username"):
                return ToolResult(success=False, error=err)

        pat = _read_github_pat()
        if pat is None:
            return _missing_pat_result(approval_request_id, operation)
        token_prefix = token_sha256_prefix(pat)

        request_body = _scrub_request_body(
            {
                "org": org,
                "team_slug": team_slug,
                "members": members,
                "removed_members": removed,
                "role": role,
                "rationale": rationale,
            }
        )

        # --- fetch live membership for diff ---
        try:
            with _build_client(pat) as client:
                live = _list_team_members(client, org, team_slug)
        except _GithubApiError as exc:
            msg = str(exc)
            logger.error("github_admin membership fetch failed: %s", msg)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary={},
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(success=False, error=f"github api error: {msg}")

        live_logins = {e["login"] for e in live}
        adds = [m for m in members if m not in live_logins]
        removes_desired = list(removed)
        removing = bool(removes_desired)

        hitl_level = _resolve_hitl_level(
            GithubAdminOperation.SET_TEAM_MEMBERSHIP, removing=removing
        )

        diff_preview = {
            "adds": adds,
            "removes": removes_desired,
            "unchanged": [m for m in members if m in live_logins],
            "live_count": len(live_logins),
        }

        # --- HITL gate: ASK when removing ---
        if hitl_level in ("ask", "ask_dual"):
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary=diff_preview,
                rationale=rationale,
                status="pending_approval",
                error_message=None,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(
                output=(
                    f"Team membership reconcile for {org}/{team_slug} pending "
                    f"{hitl_level}: +{len(adds)} / -{len(removes_desired)}."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "diff": diff_preview,
                    "token_sha256_prefix": token_prefix,
                    "operation": operation,
                },
            )

        # --- ALLOW path: execute adds ---
        applied_adds: list[str] = []
        applied_removes: list[str] = []
        try:
            with _build_client(pat) as client:
                for username in adds:
                    _set_team_membership(client, org, team_slug, username=username, role=role)
                    applied_adds.append(username)
                for username in removes_desired:
                    _remove_team_membership(client, org, team_slug, username=username)
                    applied_removes.append(username)
        except _GithubApiError as exc:
            msg = str(exc)
            logger.error("github_admin membership apply failed: %s", msg)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary={
                    **diff_preview,
                    "applied_adds": applied_adds,
                    "applied_removes": applied_removes,
                },
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(success=False, error=f"github api error: {msg}")

        response_summary = {
            **diff_preview,
            "applied_adds": applied_adds,
            "applied_removes": applied_removes,
        }
        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            operation=operation,
            target_org=org,
            target_repo=None,
            target_team_slug=team_slug,
            target_branch=None,
            token_prefix=token_prefix,
            request_body=request_body,
            response_summary=response_summary,
            rationale=rationale,
            status="applied",
            error_message=None,
            request_id=request_id if isinstance(request_id, str) else None,
        )
        return ToolResult(
            output=(
                f"Team membership reconciled for {org}/{team_slug}: "
                f"+{len(applied_adds)} / -{len(applied_removes)}."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": hitl_level,
                "diff": response_summary,
                "token_sha256_prefix": token_prefix,
                "operation": operation,
            },
        )


# ---------------------------------------------------------------------------
# Tool: set_branch_protection
# ---------------------------------------------------------------------------


class GithubAdminSetBranchProtectionTool(BaseTool):
    """``github_admin.set_branch_protection`` -- RFC 0006 Sprint 1.

    Applies a branch-protection rule on ``org/repo@branch``. Always
    ASK_DUAL in Sprint 1 (conservative); Sprint 2 will differentiate
    first-time from modify via an audit lookup.

    The ``rules`` payload is GitHub's native shape -- see
    https://docs.github.com/en/rest/branches/branch-protection -- and is
    NOT reshaped by the tool. Typical fields:

    - ``required_approving_review_count``: int
    - ``require_code_owner_reviews``: bool
    - ``required_status_checks``: {strict: bool, contexts: [str, ...]}
    - ``enforce_admins``: bool
    - ``restrictions``: null or {users:[], teams:[], apps:[]}
    """

    name = "github_admin_set_branch_protection"
    description = (
        "Apply branch-protection rules on a repo@branch. Payload follows "
        "GitHub's native branch-protection schema. Gated ASK_DUAL."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "org": {
                    "type": "string",
                    "enum": sorted(ALLOWED_ORGS),
                },
                "repo": {"type": "string"},
                "branch": {"type": "string"},
                "rules": {
                    "type": "object",
                    "description": "Native GitHub branch-protection payload.",
                },
                "rationale": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["org", "repo", "branch", "rules", "rationale"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        org = str(kwargs.get("org") or "")
        repo = str(kwargs.get("repo") or "")
        branch = str(kwargs.get("branch") or "")
        rules = kwargs.get("rules")
        rationale = str(kwargs.get("rationale") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        approval_request_id = str(uuid.uuid4())
        operation = GithubAdminOperation.SET_BRANCH_PROTECTION.value

        # --- validation ---
        if err := _validate_org(org):
            return ToolResult(success=False, error=err)
        if err := _validate_slug(repo, field="repo"):
            return ToolResult(success=False, error=err)
        if not branch or len(branch) > 255 or " " in branch:
            return ToolResult(
                success=False,
                error="branch is required (<=255 chars, no whitespace)",
            )
        if not isinstance(rules, dict) or not rules:
            return ToolResult(success=False, error="rules must be a non-empty object")
        if not rationale or len(rationale) < 10:
            return ToolResult(success=False, error="rationale is required (>=10 chars)")

        pat = _read_github_pat()
        if pat is None:
            return _missing_pat_result(approval_request_id, operation)
        token_prefix = token_sha256_prefix(pat)

        request_body = _scrub_request_body(
            {
                "org": org,
                "repo": repo,
                "branch": branch,
                "rules": rules,
                "rationale": rationale,
            }
        )

        hitl_level = _resolve_hitl_level(GithubAdminOperation.SET_BRANCH_PROTECTION, removing=False)

        # --- HITL gate: ASK_DUAL ---
        if hitl_level in ("ask", "ask_dual"):
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=repo,
                target_team_slug=None,
                target_branch=branch,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary={"rule_fields": sorted(rules.keys())},
                rationale=rationale,
                status="pending_approval",
                error_message=None,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(
                output=(
                    f"Branch protection for {org}/{repo}@{branch} pending {hitl_level} approval."
                ),
                data={
                    "approval_request_id": approval_request_id,
                    "status": "pending_approval",
                    "hitl_level": hitl_level,
                    "rule_fields": sorted(rules.keys()),
                    "token_sha256_prefix": token_prefix,
                    "operation": operation,
                },
            )

        # --- ALLOW path (test-only in Sprint 1 -- prod is always ASK_DUAL) ---
        try:
            with _build_client(pat) as client:
                applied = _set_branch_protection(client, org, repo, branch, rules=rules)
        except _GithubApiError as exc:
            msg = str(exc)
            logger.error("github_admin branch protection apply failed: %s", msg)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=repo,
                target_team_slug=None,
                target_branch=branch,
                token_prefix=token_prefix,
                request_body=request_body,
                response_summary={},
                rationale=rationale,
                status="failed",
                error_message=msg,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(success=False, error=f"github api error: {msg}")

        response_summary = {
            "rule_fields": sorted(rules.keys()),
            "url": applied.get("url"),
        }
        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            operation=operation,
            target_org=org,
            target_repo=repo,
            target_team_slug=None,
            target_branch=branch,
            token_prefix=token_prefix,
            request_body=request_body,
            response_summary=response_summary,
            rationale=rationale,
            status="applied",
            error_message=None,
            request_id=request_id if isinstance(request_id, str) else None,
        )
        return ToolResult(
            output=(f"Branch protection applied on {org}/{repo}@{branch}."),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": hitl_level,
                "rule_fields": sorted(rules.keys()),
                "token_sha256_prefix": token_prefix,
                "operation": operation,
            },
        )


# ---------------------------------------------------------------------------
# Tool: audit_team_membership (read-only, ALLOW)
# ---------------------------------------------------------------------------


class GithubAdminAuditTeamMembershipTool(BaseTool):
    """``github_admin.audit_team_membership`` -- RFC 0006 Sprint 1.

    Read-only. Returns the live member list plus a drift diff against
    the most recent ``set_team_membership`` audit row (if any). Gated
    ALLOW -- no mutation possible through this surface.

    The drift view:
    - ``expected``: the members from the last known intended state
    - ``live``: what GitHub currently reports
    - ``drift.added_on_github``: in live but not in expected
    - ``drift.removed_on_github``: in expected but not in live
    """

    name = "github_admin_audit_team_membership"
    description = (
        "Read-only audit of a GitHub team's current membership, with an "
        "optional drift diff against the last intended-state audit row. "
        "Gated ALLOW."
    )

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "org": {
                    "type": "string",
                    "enum": sorted(ALLOWED_ORGS),
                },
                "team_slug": {"type": "string"},
                "agent_id": {"type": "string"},
                "actor_user_sub": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["org", "team_slug"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        org = str(kwargs.get("org") or "")
        team_slug = str(kwargs.get("team_slug") or "")
        agent_id = kwargs.get("agent_id")
        actor_user_sub = kwargs.get("actor_user_sub")
        request_id = kwargs.get("request_id")

        approval_request_id = str(uuid.uuid4())
        operation = GithubAdminOperation.AUDIT_TEAM_MEMBERSHIP.value

        if err := _validate_org(org):
            return ToolResult(success=False, error=err)
        if err := _validate_slug(team_slug, field="team_slug"):
            return ToolResult(success=False, error=err)

        pat = _read_github_pat()
        if pat is None:
            return _missing_pat_result(approval_request_id, operation)
        token_prefix = token_sha256_prefix(pat)

        try:
            with _build_client(pat) as client:
                live = _list_team_members(client, org, team_slug)
        except _GithubApiError as exc:
            msg = str(exc)
            logger.error("github_admin audit fetch failed: %s", msg)
            _audit_record(
                approval_request_id=approval_request_id,
                agent_id=str(agent_id) if agent_id else None,
                actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
                operation=operation,
                target_org=org,
                target_repo=None,
                target_team_slug=team_slug,
                target_branch=None,
                token_prefix=token_prefix,
                request_body={"org": org, "team_slug": team_slug},
                response_summary={},
                rationale="audit: list team members",
                status="failed",
                error_message=msg,
                request_id=request_id if isinstance(request_id, str) else None,
            )
            return ToolResult(success=False, error=f"github api error: {msg}")

        # --- drift lookup (best effort) ---
        expected: list[str] | None = None
        try:
            from nexus_api.audit.github_admin_audit import (
                last_team_membership_row,
            )

            last = last_team_membership_row(org=org, team_slug=team_slug)
            if last is not None:
                body = last.request_body or {}
                raw = body.get("members")
                if isinstance(raw, list):
                    expected = [str(m) for m in raw]
        except Exception:  # noqa: BLE001 — drift lookup is best-effort
            expected = None

        live_logins = sorted({e["login"] for e in live})
        drift: dict[str, Any] = {}
        if expected is not None:
            exp_set = set(expected)
            live_set = set(live_logins)
            drift = {
                "expected": sorted(exp_set),
                "live": live_logins,
                "added_on_github": sorted(live_set - exp_set),
                "removed_on_github": sorted(exp_set - live_set),
                "has_drift": bool(live_set ^ exp_set),
            }
        else:
            drift = {
                "expected": None,
                "live": live_logins,
                "note": "no prior set_team_membership audit row; drift unknown",
            }

        response_summary = {
            "member_count": len(live_logins),
            "has_drift": bool(drift.get("has_drift")),
        }
        _audit_record(
            approval_request_id=approval_request_id,
            agent_id=str(agent_id) if agent_id else None,
            actor_user_sub=str(actor_user_sub) if actor_user_sub else None,
            operation=operation,
            target_org=org,
            target_repo=None,
            target_team_slug=team_slug,
            target_branch=None,
            token_prefix=token_prefix,
            request_body={"org": org, "team_slug": team_slug},
            response_summary=response_summary,
            rationale="audit: list team members",
            status="applied",
            error_message=None,
            request_id=request_id if isinstance(request_id, str) else None,
        )

        return ToolResult(
            output=(
                f"Team {org}/{team_slug} has {len(live_logins)} member(s); "
                f"drift={'yes' if drift.get('has_drift') else 'no'}."
            ),
            data={
                "approval_request_id": approval_request_id,
                "status": "applied",
                "hitl_level": "allow",
                "members": live,  # full [{login, role}, ...]
                "drift": drift,
                "token_sha256_prefix": token_prefix,
                "operation": operation,
            },
        )


# Audience tagging — platform-only tools. Tenant swarms are filtered
# out of these at spec-generation time by ToolRegistry.get_specs(audience=...).
for _cls in (
    GithubAdminCreateTeamTool,
    GithubAdminSetTeamMembershipTool,
    GithubAdminSetBranchProtectionTool,
    GithubAdminAuditTeamMembershipTool,
):
    _cls.audience = Audience.PLATFORM
