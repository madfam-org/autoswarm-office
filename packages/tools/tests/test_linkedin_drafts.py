"""Tests for the LinkedIn DRAFT-ONLY generator + sibling list tool.

The package is deliberately draft-only — there is no ``linkedin_post``
tool in the registry. These tests assert that, the create-tool's
validation + storage behaviour, hook-extraction quality, and the
listing tool's recent-first ordering + status filter.

NO posting code is exercised because none ships. This test file's
existence is itself documentation that the absence is intentional.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from selva_tools.audience import Audience
from selva_tools.builtins import linkedin_drafts as ld_mod
from selva_tools.builtins.linkedin_draft_list import LinkedInDraftListTool
from selva_tools.builtins.linkedin_drafts import (
    DEFAULT_MAX_CHARS,
    HOOK_CHAR_LIMIT,
    LinkedInDraftCreateTool,
    extract_hook,
)

# ---------------------------------------------------------------------------
# Storage isolation — point both tools at a tmp dir per test so writes
# don't leak across tests or pollute the developer's content store.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect both the artifact backend AND the sidecar index dir into
    ``tmp_path`` for the duration of the test.

    The sidecar index lives at ``Path(_storage._base).parent /
    'linkedin_drafts_index'`` per ``_drafts_index_dir()``, so swapping
    ``_storage._base`` automatically relocates the index too.
    """
    artifact_base = tmp_path / "artifacts"
    artifact_base.mkdir()
    # ``LocalFSStorage._base`` is a ``Path``; setting it to a ``str``
    # breaks the ``self._base / hash[:2] / ...`` join. Keep the type.
    monkeypatch.setattr(ld_mod._storage, "_base", artifact_base)
    return tmp_path


# ---------------------------------------------------------------------------
# Hook extraction quality — natural sentence boundary, hard-cut fallback,
# short-body passthrough.
# ---------------------------------------------------------------------------


class TestHookExtraction:
    def test_short_body_returned_as_is(self) -> None:
        body = "Quick post under the limit."
        assert extract_hook(body) == body

    def test_cuts_at_question_mark_inside_limit(self) -> None:
        body = (
            "Why does Mexican accounting software still feel like 2005? "
            "Karafiel rebuilds the SAT compliance flow from scratch with "
            "a real-time CFDI 4.0 stamping pipeline that takes seconds, "
            "not minutes, and integrates directly with your bank feeds."
        )
        hook = extract_hook(body)
        assert hook.endswith("?")
        assert len(hook) <= HOOK_CHAR_LIMIT
        assert "still feel like 2005?" in hook

    def test_cuts_at_period_inside_limit(self) -> None:
        body = (
            "We rebuilt our entire accounting stack in 90 days. "
            "Here is what we learned about Mexican SAT compliance, "
            "the gnarly parts of CFDI 4.0, and why the legacy ERPs "
            "are vulnerable to a focused rewrite."
        )
        hook = extract_hook(body)
        assert hook.endswith(".")
        assert len(hook) <= HOOK_CHAR_LIMIT
        assert hook.startswith("We rebuilt our entire accounting stack in 90 days.")

    def test_hard_cut_with_ellipsis_when_no_boundary(self) -> None:
        # 200 char run-on with no sentence terminators inside the first 140.
        body = (
            "this is a long run on sentence with no punctuation at all "
            "that just keeps going and going past the see more cutoff and "
            "into the body where readers must click to expand it"
        )
        hook = extract_hook(body)
        assert hook.endswith("...")
        assert len(hook) == HOOK_CHAR_LIMIT

    def test_picks_last_sentence_boundary_within_limit(self) -> None:
        # First period at char 20, second at char ~110. We want the second.
        body = (
            "First sentence ends. "  # ~20 chars
            "Second sentence finally lands inside the hundred-forty-char "
            "limit. Third sentence is way past the threshold and should "
            "not be the cut point."
        )
        hook = extract_hook(body)
        assert "Second sentence" in hook
        assert "Third sentence" not in hook
        assert hook.endswith(".")

    def test_respects_custom_limit(self) -> None:
        body = "Hello. World. Foo. Bar. Baz."
        hook = extract_hook(body, limit=15)
        assert len(hook) <= 15


# ---------------------------------------------------------------------------
# Create tool — validation, char_count accuracy, frontmatter, hook on
# the result, artifact saved at expected path.
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_audience_must_be_in_allowlist(self) -> None:
        tool = LinkedInDraftCreateTool()
        result = await tool.execute(
            audience="random_audience",
            platform="karafiel",
            topic="hi",
        )
        assert result.success is False
        assert result.error is not None
        assert "audience" in result.error

    @pytest.mark.asyncio
    async def test_platform_must_be_in_allowlist(self) -> None:
        tool = LinkedInDraftCreateTool()
        result = await tool.execute(
            audience="founders",
            platform="some_random_thing",
            topic="hi",
        )
        assert result.success is False
        assert result.error is not None
        assert "platform" in result.error

    @pytest.mark.asyncio
    async def test_tone_must_be_in_allowlist(self) -> None:
        tool = LinkedInDraftCreateTool()
        result = await tool.execute(
            audience="founders",
            platform="selva",
            topic="hi",
            tone="unhinged",
        )
        assert result.success is False
        assert result.error is not None
        assert "tone" in result.error

    @pytest.mark.asyncio
    async def test_topic_required(self) -> None:
        tool = LinkedInDraftCreateTool()
        result = await tool.execute(
            audience="founders",
            platform="selva",
            topic="   ",
        )
        assert result.success is False
        assert result.error is not None
        assert "topic" in result.error

    @pytest.mark.asyncio
    async def test_max_chars_enforced(self) -> None:
        tool = LinkedInDraftCreateTool()
        long_body = "x" * (DEFAULT_MAX_CHARS + 1)
        result = await tool.execute(
            audience="founders",
            platform="selva",
            topic="overflow",
            body=long_body,
        )
        assert result.success is False
        assert result.error is not None
        assert "max_chars" in result.error

    @pytest.mark.asyncio
    async def test_create_returns_draft_id_path_preview_charcount_hook(
        self,
    ) -> None:
        tool = LinkedInDraftCreateTool()
        body = (
            "Karafiel just shipped real-time CFDI 4.0 stamping for Mexican "
            "accountants. Why does this matter? Because the SAT compliance "
            "flow has been a 3-minute round-trip since 2018 and every other "
            "platform still calls the SAT API synchronously. We don't. We "
            "queue, dedupe, and stamp asynchronously, and the operator sees "
            "their CFDI in <2 seconds with full audit trail."
        )
        result = await tool.execute(
            audience="accountants_mx",
            platform="karafiel",
            topic="real-time CFDI 4.0 stamping launch",
            body=body,
        )
        assert result.success is True, result.error

        d = result.data
        assert "draft_id" in d
        assert isinstance(d["draft_id"], str) and len(d["draft_id"]) >= 32
        assert "draft_path" in d  # storage path of the artifact blob
        assert d["preview"] == body[:200]
        assert d["char_count"] == len(body)
        assert d["hook"]
        assert len(d["hook"]) <= HOOK_CHAR_LIMIT
        assert d["audience"] == "accountants_mx"
        assert d["platform"] == "karafiel"
        assert d["status"] == "draft"
        assert "logical_path" in d
        # Logical path: linkedin_drafts/<YYYY-MM-DD>/<draft_id>.md
        assert re.match(
            r"^linkedin_drafts/\d{4}-\d{2}-\d{2}/" + re.escape(d["draft_id"]) + r"\.md$",
            d["logical_path"],
        )

    @pytest.mark.asyncio
    async def test_create_writes_frontmatter_with_expected_keys(self) -> None:
        tool = LinkedInDraftCreateTool()
        body = "Founders: stop building features. Start measuring retention."
        result = await tool.execute(
            audience="founders",
            platform="dhanam",
            topic="retention > features",
            body=body,
            tone="thought-leader",
        )
        assert result.success is True

        # Read back the saved markdown directly from artifact storage.
        artifact_path = Path(result.data["draft_path"])
        assert artifact_path.exists()
        markdown = artifact_path.read_text(encoding="utf-8")

        # Frontmatter sanity.
        assert markdown.startswith("---\n")
        assert f"draft_id: {result.data['draft_id']}\n" in markdown
        assert "audience: founders\n" in markdown
        assert "platform: dhanam\n" in markdown
        assert "status: draft\n" in markdown
        assert f"char_count: {len(body)}\n" in markdown
        # Topic stored as quoted YAML scalar.
        assert "topic: 'retention > features'\n" in markdown

        # Body present.
        assert body in markdown

        # Operator instructions present + the AI-disclosure warning.
        assert "**HOOK**" in markdown
        assert "TO POST" in markdown
        assert "DO NOT" in markdown
        assert "AI generated" in markdown

    @pytest.mark.asyncio
    async def test_char_count_matches_body_length_exactly(self) -> None:
        tool = LinkedInDraftCreateTool()
        body = "a" * 1234
        result = await tool.execute(
            audience="developers",
            platform="selva",
            topic="benchmark",
            body=body,
        )
        assert result.success is True
        assert result.data["char_count"] == 1234

    @pytest.mark.asyncio
    async def test_artifact_saved_at_expected_path(self, tmp_path: Path) -> None:
        """The artifact lives at the content-addressable storage path
        returned in ``draft_path`` AND the sidecar index file is at
        ``linkedin_drafts_index/<date>/<draft_id>.idx``."""
        tool = LinkedInDraftCreateTool()
        body = "Sample body."
        result = await tool.execute(
            audience="ctos",
            platform="cotiza",
            topic="sample",
            body=body,
        )
        assert result.success is True

        artifact_path = Path(result.data["draft_path"])
        assert artifact_path.exists()
        assert artifact_path.is_file()

        # Sidecar index file
        index_dir = ld_mod._drafts_index_dir()
        # Find the .idx file (don't reach into the date subdir blindly —
        # the date is always today UTC).
        idx_files = list(index_dir.rglob(f"{result.data['draft_id']}.idx"))
        assert len(idx_files) == 1
        idx_path = idx_files[0]
        # Index file points at the artifact storage path.
        assert idx_path.read_text(encoding="utf-8").strip() == str(artifact_path)
        # Index file lives under a YYYY-MM-DD subdir.
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", idx_path.parent.name)

    @pytest.mark.asyncio
    async def test_no_body_uses_topic_as_body(self) -> None:
        """When ``body`` is omitted, the topic doubles as a stub body so
        downstream hook + preview are still well-defined."""
        tool = LinkedInDraftCreateTool()
        result = await tool.execute(
            audience="b2b_buyers",
            platform="forj",
            topic="why scoping matters",
        )
        assert result.success is True
        assert result.data["preview"] == "why scoping matters"
        assert result.data["char_count"] == len("why scoping matters")


# ---------------------------------------------------------------------------
# Hook extraction quality (140-char rule from the create result).
# ---------------------------------------------------------------------------


class TestCreateHookField:
    @pytest.mark.asyncio
    async def test_hook_stops_at_first_period_within_limit(self) -> None:
        tool = LinkedInDraftCreateTool()
        body = (
            "We rebuilt our quoting engine in 30 days. "
            "Here is what we learned about Mexican B2B procurement "
            "and why legacy ERPs cannot compete with a clean rewrite."
        )
        result = await tool.execute(
            audience="founders",
            platform="cotiza",
            topic="quoting engine rebuild",
            body=body,
        )
        assert result.success is True
        hook = result.data["hook"]
        assert hook.endswith(".")
        assert len(hook) <= HOOK_CHAR_LIMIT


# ---------------------------------------------------------------------------
# List tool — recent-first, status filter, empty when nothing staged.
# ---------------------------------------------------------------------------


class TestList:
    @pytest.mark.asyncio
    async def test_empty_when_no_drafts_staged(self) -> None:
        tool = LinkedInDraftListTool()
        result = await tool.execute()
        assert result.success is True
        assert result.data["drafts"] == []

    @pytest.mark.asyncio
    async def test_returns_recent_drafts(self) -> None:
        create = LinkedInDraftCreateTool()
        for i in range(3):
            r = await create.execute(
                audience="founders",
                platform="selva",
                topic=f"draft number {i}",
                body=f"body number {i} with some content",
            )
            assert r.success is True

        list_tool = LinkedInDraftListTool()
        result = await list_tool.execute(limit=10)
        assert result.success is True
        drafts = result.data["drafts"]
        assert len(drafts) == 3
        topics = {d["topic"] for d in drafts}
        assert topics == {"draft number 0", "draft number 1", "draft number 2"}

        for d in drafts:
            assert d["status"] == "draft"
            assert d["audience"] == "founders"
            assert d["platform"] == "selva"
            assert d["char_count"] > 0
            assert d["draft_id"]
            assert d["storage_path"]
            assert d["logical_path"].startswith("linkedin_drafts/")

    @pytest.mark.asyncio
    async def test_limit_caps_returned_drafts(self) -> None:
        create = LinkedInDraftCreateTool()
        for i in range(5):
            await create.execute(
                audience="founders",
                platform="selva",
                topic=f"draft {i}",
                body=f"body {i}",
            )

        list_tool = LinkedInDraftListTool()
        result = await list_tool.execute(limit=2)
        assert result.success is True
        assert len(result.data["drafts"]) == 2

    @pytest.mark.asyncio
    async def test_status_filter_excludes_non_matching(self) -> None:
        # Stage one draft normally — status will be 'draft'.
        create = LinkedInDraftCreateTool()
        r = await create.execute(
            audience="ctos",
            platform="dhanam",
            topic="alpha",
            body="alpha body",
        )
        assert r.success is True

        list_tool = LinkedInDraftListTool()
        # Filtering by an unknown status should yield zero results.
        result = await list_tool.execute(status="published")
        assert result.success is True
        assert result.data["drafts"] == []
        assert result.data["status"] == "published"


# ---------------------------------------------------------------------------
# Audience tag — tools must be TENANT (default), so any tenant swarm
# can stage drafts for their own org.
# ---------------------------------------------------------------------------


class TestAudience:
    def test_create_tool_is_tenant(self) -> None:
        assert LinkedInDraftCreateTool.audience is Audience.TENANT

    def test_list_tool_is_tenant(self) -> None:
        assert LinkedInDraftListTool.audience is Audience.TENANT


# ---------------------------------------------------------------------------
# No posting — guard against future regressions.
# ---------------------------------------------------------------------------


class TestNoPostingTool:
    """The package is draft-only by design. Any new module attribute or
    builtin tool whose name contains ``post`` would be a regression.
    """

    def test_no_post_attr_on_drafts_module(self) -> None:
        for attr in dir(ld_mod):
            assert "post" not in attr.lower(), (
                f"Found suspicious attribute '{attr}' in linkedin_drafts module — "
                "this package is DRAFT-ONLY. No posting code should ship."
            )

    def test_builtin_registry_has_no_linkedin_post_tool(self) -> None:
        from selva_tools.builtins import get_builtin_tools

        tools: list[Any] = get_builtin_tools()
        names = {t.name for t in tools}
        # Sanity: our two tools ARE registered.
        assert "linkedin_draft_create" in names
        assert "linkedin_draft_list" in names
        # The forbidden tool name MUST NOT exist.
        assert "linkedin_post" not in names
        # Defense in depth: no tool name should start with linkedin_ and
        # include the word "post" without "draft".
        for name in names:
            if name.startswith("linkedin_"):
                assert "draft" in name, (
                    f"LinkedIn tool '{name}' is not draft-only — "
                    "this package only ships draft tools."
                )
