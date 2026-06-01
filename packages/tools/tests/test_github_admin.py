"""RFC 0006 Sprint 1 -- tests for ``github_admin.*``.

These tests exercise the four ``github_admin_*`` tools at the unit
level. The GitHub REST API and the nexus-api audit module are stubbed
so tests run with no network and no DB.

Invariants under test (each maps to one or more tests below):

1.  create_team happy path -- ASK gate produces pending_approval; no
    API traffic on mutate until approval arrives.
2.  create_team idempotency -- a second call with the same slug returns
    ``status="already_exists"`` without POSTing.
3.  create_team input validation -- org allow-list, slug, privacy,
    rationale all rejected cleanly without leaking the PAT.
4.  set_team_membership add-only -> ALLOW, applies adds.
5.  set_team_membership with removals -> ASK, pending_approval.
6.  set_branch_protection always ASK_DUAL in Sprint 1; pending_approval.
7.  audit_team_membership returns live + drift diff; ALLOW.
8.  Missing PAT -> failed ToolResult with structured error, no leak.
9.  GitHub 403/500 -> failed audit row + scrubbed error message.
10. SHA-256 prefix redaction -- PAT never appears in audit payload or
    returned data; only the 8-hex prefix does.
11. HITL denial path for ``create_team`` -- ASK -> pending_approval row
    is written with status="pending_approval" and the API is untouched.
12. dry-run equivalent -- the pending_approval path is the dry-run.
13. Source lint -- the tool file never passes the ``pat`` / ``token``
    identifier through a logger or into a ToolResult.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from selva_tools.base import ToolResult
from selva_tools.builtins import github_admin as gh_admin_mod
from selva_tools.builtins.github_admin import (
    ALLOWED_ORGS,
    GithubAdminAuditTeamMembershipTool,
    GithubAdminCreateTeamTool,
    GithubAdminSetBranchProtectionTool,
    GithubAdminSetTeamMembershipTool,
    token_sha256_prefix,
)

# A PAT value that must never appear in logs, data, or errors.
FAKE_PAT = "DUMMY_GITHUB_TOKEN_DO_NOT_USE"
FAKE_PAT_PREFIX = token_sha256_prefix(FAKE_PAT)


# ---------------------------------------------------------------------------
# httpx MockTransport -- intercepts all GitHub API calls
# ---------------------------------------------------------------------------


class _FakeGithubServer:
    """In-memory GitHub replica -- just the endpoints we exercise."""

    def __init__(self) -> None:
        # org -> slug -> team dict
        self.teams: dict[str, dict[str, dict[str, Any]]] = {}
        # (org, slug) -> list of {login, role}
        self.memberships: dict[tuple[str, str], list[dict[str, str]]] = {}
        # (org, repo, branch) -> rules
        self.branch_protection: dict[tuple[str, str, str], dict[str, Any]] = {}
        # Override next GET /orgs/.../teams/<slug> to return this status.
        self.next_get_team_status: int | None = None
        # Override next POST /orgs/.../teams to return this status.
        self.next_create_team_status: int | None = None
        # Override next PUT on branch protection.
        self.next_branch_protection_status: int | None = None
        self.calls: list[tuple[str, str]] = []  # (method, path)

    def seed_team(
        self,
        org: str,
        slug: str,
        *,
        members: list[dict[str, str]] | None = None,
    ) -> None:
        org_teams = self.teams.setdefault(org, {})
        org_teams[slug] = {
            "id": 10000 + len(org_teams),
            "slug": slug,
            "name": slug.title(),
            "privacy": "closed",
        }
        self.memberships[(org, slug)] = list(members or [])

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.method
        path = request.url.path
        self.calls.append((method, path))

        # GET /orgs/{org}/teams/{team_slug}
        m = re.fullmatch(r"/orgs/([^/]+)/teams/([^/]+)", path)
        if m and method == "GET":
            if self.next_get_team_status is not None:
                status = self.next_get_team_status
                self.next_get_team_status = None
                return httpx.Response(status, json={"message": "forced"})
            org, slug = m.group(1), m.group(2)
            team = self.teams.get(org, {}).get(slug)
            if team is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json=team)

        # POST /orgs/{org}/teams
        m = re.fullmatch(r"/orgs/([^/]+)/teams", path)
        if m and method == "POST":
            if self.next_create_team_status is not None:
                status = self.next_create_team_status
                self.next_create_team_status = None
                return httpx.Response(status, json={"message": "forced"})
            org = m.group(1)
            body = json.loads(request.content)
            slug = body["name"].lower().replace(" ", "-")
            team = {
                "id": 20000 + len(self.teams.get(org, {})),
                "slug": slug,
                "name": body["name"],
                "privacy": body.get("privacy", "closed"),
            }
            self.teams.setdefault(org, {})[slug] = team
            self.memberships.setdefault((org, slug), [])
            return httpx.Response(201, json=team)

        # GET /orgs/{org}/teams/{team}/members?role=...
        m = re.fullmatch(r"/orgs/([^/]+)/teams/([^/]+)/members", path)
        if m and method == "GET":
            org, slug = m.group(1), m.group(2)
            role = request.url.params.get("role", "member")
            if (org, slug) not in self.memberships:
                return httpx.Response(404, json={"message": "Not Found"})
            filtered = [
                {"login": e["login"]} for e in self.memberships[(org, slug)] if e["role"] == role
            ]
            return httpx.Response(200, json=filtered)

        # PUT /orgs/{org}/teams/{team}/memberships/{username}
        m = re.fullmatch(r"/orgs/([^/]+)/teams/([^/]+)/memberships/([^/]+)", path)
        if m and method == "PUT":
            org, slug, username = m.group(1), m.group(2), m.group(3)
            body = json.loads(request.content)
            role = body.get("role", "member")
            members = self.memberships.setdefault((org, slug), [])
            # Upsert.
            existing = next((e for e in members if e["login"] == username), None)
            if existing is not None:
                existing["role"] = role
            else:
                members.append({"login": username, "role": role})
            return httpx.Response(200, json={"url": path, "role": role, "state": "active"})

        # DELETE /orgs/{org}/teams/{team}/memberships/{username}
        if m and method == "DELETE":
            org, slug, username = m.group(1), m.group(2), m.group(3)
            members = self.memberships.setdefault((org, slug), [])
            self.memberships[(org, slug)] = [e for e in members if e["login"] != username]
            return httpx.Response(204)

        # PUT /repos/{org}/{repo}/branches/{branch}/protection
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)/branches/([^/]+)/protection", path)
        if m and method == "PUT":
            if self.next_branch_protection_status is not None:
                status = self.next_branch_protection_status
                self.next_branch_protection_status = None
                return httpx.Response(status, json={"message": "forced"})
            org, repo, branch = m.group(1), m.group(2), m.group(3)
            rules = json.loads(request.content)
            self.branch_protection[(org, repo, branch)] = rules
            return httpx.Response(
                200,
                json={
                    "url": f"https://api.github.com{path}",
                    "required_pull_request_reviews": rules.get("required_pull_request_reviews"),
                },
            )

        return httpx.Response(404, json={"message": f"unmatched {method} {path}"})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_gh() -> _FakeGithubServer:
    return _FakeGithubServer()


@pytest.fixture
def audit_spy() -> dict[str, Any]:
    """Capture everything the tool would have written to ``github_admin_audit_log``."""
    spy: dict[str, Any] = {"rows": []}

    def fake_append(**kwargs: Any) -> None:
        spy["rows"].append(kwargs)

    spy["append_fn"] = fake_append
    return spy


@pytest.fixture
def wire(
    monkeypatch: pytest.MonkeyPatch,
    fake_gh: _FakeGithubServer,
    audit_spy: dict[str, Any],
) -> dict[str, Any]:
    """Patch PAT lookup, the httpx client builder, and the audit recorder."""

    def fake_read_pat() -> str:
        return FAKE_PAT

    def fake_build_client(token: str) -> httpx.Client:
        # Build a real httpx.Client but pipe every request through the fake.
        return httpx.Client(
            base_url=gh_admin_mod.GITHUB_API_BASE,
            timeout=5.0,
            transport=httpx.MockTransport(fake_gh.handler),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "selva-github-admin-test/0.1",
            },
        )

    monkeypatch.setattr(gh_admin_mod, "_read_github_pat", fake_read_pat, raising=True)
    monkeypatch.setattr(gh_admin_mod, "_build_client", fake_build_client, raising=True)
    monkeypatch.setattr(
        gh_admin_mod,
        "_audit_record",
        lambda **kw: audit_spy["append_fn"](**kw),
        raising=True,
    )
    return {"gh": fake_gh, "spy": audit_spy}


def _assert_no_pat_leak(blob: str) -> None:
    assert FAKE_PAT not in blob, "PAT value leaked into returned text!"


# ===========================================================================
# Tool: create_team
# ===========================================================================


# 1. create_team new-slug -> ASK gate -> pending_approval, API not called.
async def test_create_team_asks_on_new_slug(
    wire: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="selva.tools.github_admin")
    tool = GithubAdminCreateTeamTool()

    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        team_name="Platform",
        description="Platform team for infra",
        privacy="closed",
        rationale="bootstrap Q4 CODEOWNERS per RFC 0001",
    )

    assert isinstance(result, ToolResult)
    assert result.success is True, result.error
    assert result.data["status"] == "pending_approval"
    assert result.data["hitl_level"] == "ask"
    assert result.data["token_sha256_prefix"] == FAKE_PAT_PREFIX
    assert "approval_request_id" in result.data

    # Only the idempotency GET was issued; no POST yet.
    gh = wire["gh"]
    assert ("GET", "/orgs/madfam-org/teams/platform") in gh.calls
    assert not any(
        method == "POST" and path == "/orgs/madfam-org/teams" for method, path in gh.calls
    )

    # Exactly one pending_approval audit row.
    rows = wire["spy"]["rows"]
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "pending_approval"
    assert row["operation"] == "create_team"
    assert row["target_org"] == "madfam-org"
    assert row["target_team_slug"] == "platform"
    assert row["token_prefix"] == FAKE_PAT_PREFIX

    # No PAT leak anywhere.
    for rec in caplog.records:
        _assert_no_pat_leak(rec.getMessage())
    _assert_no_pat_leak(str(result.data))
    _assert_no_pat_leak(str(rows))


# 2. Idempotency: existing slug short-circuits to already_exists.
async def test_create_team_idempotent_on_existing_slug(
    wire: dict[str, Any],
) -> None:
    wire["gh"].seed_team("madfam-org", "platform")
    tool = GithubAdminCreateTeamTool()

    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        team_name="Platform",
        description="already there",
        rationale="idempotent retry after previous successful create",
    )

    assert result.success is True
    assert result.data["status"] == "already_exists"
    assert result.data["team_slug"] == "platform"

    # Never POSTed -- idempotency hit.
    assert not any(method == "POST" for method, _ in wire["gh"].calls)
    # Audit row written with status=applied (no-op is still a successful outcome).
    rows = wire["spy"]["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "applied"
    assert rows[0]["response_summary"]["already_existed"] is True


# 3a. org allow-list rejection.
async def test_create_team_rejects_unknown_org(wire: dict[str, Any]) -> None:
    tool = GithubAdminCreateTeamTool()
    result = await tool.execute(
        org="not-our-org",
        team_slug="platform",
        team_name="Platform",
        description="x",
        rationale="rationale long enough",
    )
    assert result.success is False
    assert "allow-list" in (result.error or "")
    assert "not-our-org" in (result.error or "")
    _assert_no_pat_leak(result.error or "")
    # No API call, no audit row.
    assert wire["gh"].calls == []
    assert wire["spy"]["rows"] == []


# 3b. bad slug rejected.
async def test_create_team_rejects_bad_slug(wire: dict[str, Any]) -> None:
    tool = GithubAdminCreateTeamTool()
    result = await tool.execute(
        org="madfam-org",
        team_slug="invalid slug with spaces",
        team_name="X",
        description="x",
        rationale="sufficiently long rationale",
    )
    assert result.success is False
    assert "whitespace" in (result.error or "")


# 3c. missing rationale rejected.
async def test_create_team_rejects_short_rationale(wire: dict[str, Any]) -> None:
    tool = GithubAdminCreateTeamTool()
    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        team_name="Platform",
        description="x",
        rationale="too short",
    )
    assert result.success is False
    assert "rationale" in (result.error or "").lower()


# 3d. bad privacy rejected.
async def test_create_team_rejects_bad_privacy(wire: dict[str, Any]) -> None:
    tool = GithubAdminCreateTeamTool()
    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        team_name="Platform",
        description="x",
        privacy="public",  # not in ALLOWED_PRIVACY
        rationale="rationale long enough to pass",
    )
    assert result.success is False
    assert "privacy" in (result.error or "").lower()


# 8. Missing PAT.
async def test_create_team_missing_pat(
    monkeypatch: pytest.MonkeyPatch,
    audit_spy: dict[str, Any],
) -> None:
    monkeypatch.setattr(gh_admin_mod, "_read_github_pat", lambda: None, raising=True)
    monkeypatch.setattr(
        gh_admin_mod,
        "_audit_record",
        lambda **kw: audit_spy["append_fn"](**kw),
        raising=True,
    )

    tool = GithubAdminCreateTeamTool()
    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        team_name="Platform",
        description="x",
        rationale="rationale long enough to pass",
    )
    assert result.success is False
    assert "PAT" in (result.error or "") or "pat" in (result.error or "")
    assert "selva-github-admin-token" in (result.error or "")
    # No audit row written when PAT is missing (nothing actionable to record).
    assert audit_spy["rows"] == []


# 9. 403 from API writes failed audit row, scrubbed error.
async def test_create_team_403_from_api(
    wire: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger="selva.tools.github_admin")
    wire["gh"].next_get_team_status = 403
    tool = GithubAdminCreateTeamTool()

    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        team_name="Platform",
        description="x",
        rationale="rationale long enough to pass",
    )
    assert result.success is False
    assert "github api error" in (result.error or "").lower()
    assert "403" in (result.error or "")
    _assert_no_pat_leak(result.error or "")

    rows = wire["spy"]["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error_message"]
    for rec in caplog.records:
        _assert_no_pat_leak(rec.getMessage())


# ===========================================================================
# Tool: set_team_membership
# ===========================================================================


# 4. Add-only -> ALLOW path.
async def test_set_team_membership_add_only_applies(
    wire: dict[str, Any],
) -> None:
    wire["gh"].seed_team(
        "madfam-org",
        "platform",
        members=[{"login": "alice", "role": "member"}],
    )
    tool = GithubAdminSetTeamMembershipTool()

    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        members=["alice", "bob"],  # bob is the add; alice unchanged
        role="member",
        rationale="adding bob to platform team per RFC 0001 Q4 rollout",
    )

    assert result.success is True
    assert result.data["status"] == "applied"
    assert result.data["hitl_level"] == "allow"
    diff = result.data["diff"]
    assert diff["applied_adds"] == ["bob"]
    assert diff["applied_removes"] == []
    assert diff["unchanged"] == ["alice"]

    # Live state now includes both.
    live = wire["gh"].memberships[("madfam-org", "platform")]
    assert {m["login"] for m in live} == {"alice", "bob"}

    rows = wire["spy"]["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "applied"
    assert rows[0]["response_summary"]["applied_adds"] == ["bob"]


# 5. Removals escalate to ASK -> pending_approval.
async def test_set_team_membership_removal_asks(wire: dict[str, Any]) -> None:
    wire["gh"].seed_team(
        "madfam-org",
        "platform",
        members=[
            {"login": "alice", "role": "member"},
            {"login": "bob", "role": "member"},
        ],
    )
    tool = GithubAdminSetTeamMembershipTool()

    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        members=["alice"],
        removed_members=["bob"],
        rationale="bob left the team; removing per offboarding runbook ops-042",
    )

    assert result.success is True
    assert result.data["status"] == "pending_approval"
    assert result.data["hitl_level"] == "ask"

    # Live state unchanged -- the gate held.
    live = wire["gh"].memberships[("madfam-org", "platform")]
    assert {m["login"] for m in live} == {"alice", "bob"}

    # One pending row.
    rows = wire["spy"]["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "pending_approval"
    assert "bob" in rows[0]["response_summary"]["removes"]


# set_team_membership missing rationale.
async def test_set_team_membership_rejects_short_rationale(
    wire: dict[str, Any],
) -> None:
    tool = GithubAdminSetTeamMembershipTool()
    result = await tool.execute(
        org="madfam-org",
        team_slug="platform",
        members=["alice"],
        rationale="hi",
    )
    assert result.success is False
    assert "rationale" in (result.error or "").lower()


# ===========================================================================
# Tool: set_branch_protection
# ===========================================================================


# 6a. Always ASK_DUAL in Sprint 1 -> pending_approval.
async def test_set_branch_protection_always_ask_dual(
    wire: dict[str, Any],
) -> None:
    tool = GithubAdminSetBranchProtectionTool()
    result = await tool.execute(
        org="madfam-org",
        repo="karafiel",
        branch="main",
        rules={
            "required_pull_request_reviews": {
                "require_code_owner_reviews": True,
                "required_approving_review_count": 1,
            },
            "enforce_admins": True,
            "required_status_checks": None,
            "restrictions": None,
        },
        rationale="enable CODEOWNERS review on main per RFC 0001 Q4",
    )

    assert result.success is True
    assert result.data["status"] == "pending_approval"
    assert result.data["hitl_level"] == "ask_dual"
    # API never called yet -- ASK_DUAL holds.
    assert not any(method == "PUT" and "branches" in path for method, path in wire["gh"].calls)
    rows = wire["spy"]["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "pending_approval"
    assert rows[0]["target_repo"] == "karafiel"
    assert rows[0]["target_branch"] == "main"


# 6b. Invalid rules rejected.
async def test_set_branch_protection_rejects_empty_rules(
    wire: dict[str, Any],
) -> None:
    tool = GithubAdminSetBranchProtectionTool()
    result = await tool.execute(
        org="madfam-org",
        repo="karafiel",
        branch="main",
        rules={},
        rationale="rationale long enough to pass validation",
    )
    assert result.success is False
    assert "rules" in (result.error or "").lower()


# ===========================================================================
# Tool: audit_team_membership (read-only, ALLOW)
# ===========================================================================


# 7. audit returns live + drift diff.
async def test_audit_team_membership_returns_live_list(
    wire: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire["gh"].seed_team(
        "madfam-org",
        "platform",
        members=[
            {"login": "alice", "role": "member"},
            {"login": "bob", "role": "maintainer"},
            {"login": "mallory", "role": "member"},  # added out-of-band
        ],
    )

    # Stub the drift lookup so "expected" is known from a prior audit row.
    fake_last = MagicMock()
    fake_last.request_body = {"members": ["alice", "bob"]}

    def fake_last_row(**kwargs: Any) -> Any:
        return fake_last

    import sys
    import types as _types

    # Install a minimal nexus_api.audit.github_admin_audit stub.
    nexus_audit_mod = _types.ModuleType("nexus_api.audit.github_admin_audit")
    nexus_audit_mod.last_team_membership_row = fake_last_row  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "nexus_api.audit.github_admin_audit", nexus_audit_mod)
    # Also install the parent packages if absent -- don't collide with real.
    if "nexus_api" not in sys.modules:
        monkeypatch.setitem(sys.modules, "nexus_api", _types.ModuleType("nexus_api"))
    if "nexus_api.audit" not in sys.modules:
        monkeypatch.setitem(sys.modules, "nexus_api.audit", _types.ModuleType("nexus_api.audit"))

    tool = GithubAdminAuditTeamMembershipTool()
    result = await tool.execute(org="madfam-org", team_slug="platform")

    assert result.success is True
    assert result.data["status"] == "applied"
    assert result.data["hitl_level"] == "allow"

    members = result.data["members"]
    assert {m["login"] for m in members} == {"alice", "bob", "mallory"}

    drift = result.data["drift"]
    assert drift["has_drift"] is True
    assert "mallory" in drift["added_on_github"]
    assert drift["removed_on_github"] == []

    # One audit row with status=applied.
    rows = wire["spy"]["rows"]
    assert len(rows) == 1
    assert rows[0]["status"] == "applied"
    assert rows[0]["operation"] == "audit_team_membership"


# ===========================================================================
# 10. SHA-256 redaction / PAT never leaks
# ===========================================================================


async def test_pat_never_appears_in_audit_or_result(
    wire: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """End-to-end: run every tool, check the PAT never appears anywhere."""
    caplog.set_level(logging.DEBUG, logger="selva.tools.github_admin")

    t_create = GithubAdminCreateTeamTool()
    t_members = GithubAdminSetTeamMembershipTool()
    t_protect = GithubAdminSetBranchProtectionTool()
    t_audit = GithubAdminAuditTeamMembershipTool()

    wire["gh"].seed_team(
        "madfam-org",
        "platform",
        members=[{"login": "alice", "role": "member"}],
    )

    results: list[ToolResult] = []
    results.append(
        await t_create.execute(
            org="madfam-org",
            team_slug="production-reviewers",
            team_name="Production Reviewers",
            description="reviewers for prod-critical paths",
            rationale="bootstrap RFC 0001 Q4 reviewer pool",
        )
    )
    results.append(
        await t_members.execute(
            org="madfam-org",
            team_slug="platform",
            members=["alice", "bob"],
            rationale="add bob to platform team per onboarding ops-123",
        )
    )
    results.append(
        await t_protect.execute(
            org="madfam-org",
            repo="karafiel",
            branch="main",
            rules={"enforce_admins": True},
            rationale="enable admin enforcement on main branch of karafiel",
        )
    )
    results.append(await t_audit.execute(org="madfam-org", team_slug="platform"))

    # PAT must not appear anywhere.
    for r in results:
        _assert_no_pat_leak(r.output or "")
        _assert_no_pat_leak(r.error or "")
        _assert_no_pat_leak(str(r.data))
    for rec in caplog.records:
        _assert_no_pat_leak(rec.getMessage())
    for row in wire["spy"]["rows"]:
        # Serialised audit dict must not contain the PAT.
        assert FAKE_PAT not in json.dumps(row, default=str)
        # token_prefix must be exactly 8 hex chars matching SHA-256(PAT)[:8].
        assert row["token_prefix"] == FAKE_PAT_PREFIX
        assert len(row["token_prefix"]) == 8


# 10b. SHA-256 prefix function is deterministic + prefix shape.
def test_token_sha256_prefix_shape() -> None:
    prefix = token_sha256_prefix(FAKE_PAT)
    assert len(prefix) == 8
    # Hex chars only.
    assert re.fullmatch(r"[0-9a-f]{8}", prefix)
    # Deterministic.
    assert token_sha256_prefix(FAKE_PAT) == prefix


# 10c. _scrub_request_body redacts sensitive keys (defense in depth).
def test_scrub_request_body_redacts_sensitive_keys() -> None:
    from selva_tools.builtins.github_admin import _scrub_request_body

    raw = {
        "org": "madfam-org",
        "team_slug": "platform",
        "token": "this-should-never-be-logged",
        "api_key": "another-one",
        "Password": "case-insensitive-match",
        "rationale": "normal field stays intact",
    }
    scrubbed = _scrub_request_body(raw)
    assert scrubbed["org"] == "madfam-org"
    assert scrubbed["team_slug"] == "platform"
    assert scrubbed["rationale"] == "normal field stays intact"
    for k in ("token", "api_key", "Password"):
        assert scrubbed[k].startswith("redacted:sha256:")
        assert "this-should-never-be-logged" not in scrubbed[k]
        assert "another-one" not in scrubbed[k]


# ===========================================================================
# 11. HITL pending path writes a well-formed audit row
# ===========================================================================


async def test_hitl_pending_row_has_all_fields(wire: dict[str, Any]) -> None:
    tool = GithubAdminCreateTeamTool()
    await tool.execute(
        org="madfam-org",
        team_slug="platform",
        team_name="Platform",
        description="platform team",
        rationale="sufficient rationale for create_team",
        actor_user_sub="auth0|alice",
        request_id="req-abc-123",
    )
    row = wire["spy"]["rows"][0]
    assert row["status"] == "pending_approval"
    assert row["actor_user_sub"] == "auth0|alice"
    assert row["request_id"] == "req-abc-123"
    assert row["target_org"] == "madfam-org"
    assert row["target_team_slug"] == "platform"
    assert row["token_prefix"] == FAKE_PAT_PREFIX
    assert "approval_request_id" in row


# ===========================================================================
# 12. Sanity: ALLOWED_ORGS is a frozenset
# ===========================================================================


def test_allowed_orgs_is_frozenset() -> None:
    assert isinstance(ALLOWED_ORGS, frozenset)
    assert "madfam-org" in ALLOWED_ORGS


# ===========================================================================
# 13. Source-level lint -- the ``pat`` identifier never reaches a logger
# ===========================================================================


def _strip_strings_and_comments(source: str) -> str:
    """Remove string literals and comments before linting."""
    no_comments = re.sub(r"#[^\n]*", "", source)
    no_triple = re.sub(r'"""[\s\S]*?"""', '""', no_comments)
    no_triple = re.sub(r"'''[\s\S]*?'''", "''", no_triple)
    no_strings = re.sub(r'(?:rb|br|r|b|f|rf|fr)?"(?:\\.|[^"\\\n])*"', '""', no_triple)
    no_strings = re.sub(r"(?:rb|br|r|b|f|rf|fr)?'(?:\\.|[^'\\\n])*'", "''", no_strings)
    return no_strings


def test_tool_source_never_logs_raw_pat() -> None:
    """Static lint on the tool source -- the ``pat`` local var must only
    appear in approved sites (``token_sha256_prefix(pat)``,
    ``_build_client(pat)``, and control-flow checks).

    Catches accidents like ``logger.info("pat=%s", pat)`` or
    ``return ToolResult(data={"pat": pat})``.
    """
    src_path = Path(gh_admin_mod.__file__).resolve()
    source_raw = src_path.read_text(encoding="utf-8")
    source = _strip_strings_and_comments(source_raw)

    forbidden_patterns: list[tuple[str, str]] = [
        # logger.<level>(... pat ...) or ... token ...
        (
            r"logger\.(?:debug|info|warning|error|critical)\([^)]*\bpat\b[^)]*\)",
            "logger.<level>(... pat ...)",
        ),
        # Returning the PAT value.
        (r"\breturn\s+pat\b", "return pat"),
        # str(pat) / repr(pat) would leak in log args.
        (r"\bstr\(\s*pat\s*\)", "str(pat)"),
        (r"\brepr\(\s*pat\s*\)", "repr(pat)"),
        # pat in .format args.
        (r"\.format\([^)]*\bpat\b[^)]*\)", ".format(... pat ...)"),
        # ToolResult that includes ``pat`` as an identifier.
        (
            r"ToolResult\([^)]*\bpat\b[^)]*\)",
            "ToolResult(... pat ...)",
        ),
    ]

    offenders: list[tuple[str, str]] = []
    for pattern, label in forbidden_patterns:
        for m in re.finditer(pattern, source):
            line_start = source.rfind("\n", 0, m.start()) + 1
            line_end = source.find("\n", m.end())
            if line_end == -1:
                line_end = len(source)
            line = source[line_start:line_end]
            offenders.append((label, line.strip()))

    assert offenders == [], (
        "Forbidden use of `pat` identifier in tool source "
        f"-- would leak GitHub PAT. Offenders: {offenders}"
    )
    # Positive check: the approved sites exist.
    assert "token_sha256_prefix(pat)" in source_raw
    assert "_build_client(pat)" in source_raw
