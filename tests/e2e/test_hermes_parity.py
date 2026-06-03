"""Tests for the final Hermes parity sprint.

Covers:
- LLM skill synthesis (stub fallback path, since no live LLM in CI)
- HonchoProfiler preference injection
- FTS5 transcript persistence from QA Oracle
"""

from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# QA Oracle — Skill Compilation (stub path)
# ---------------------------------------------------------------------------


def test_qa_oracle_validate_and_compile_skill(tmp_path, monkeypatch):
    """validate() should write a .py skill file to the skills directory."""
    monkeypatch.setenv("SELVA_SKILLS_DIR", str(tmp_path))

    from selva_workflows.acp_qa_oracle import ACPQAOracleNode

    node = ACPQAOracleNode(
        source_code="def hello(): return 'world'",
        test_suite="assert hello() == 'world'",
    )
    result = node.validate(run_id="test-run-001")

    assert result is True
    skill_files = list(tmp_path.glob("*.py"))
    assert len(skill_files) == 1, "Expected exactly one compiled skill file"

    content = skill_files[0].read_text()
    assert "SKILL_ENTRYPOINT" in content


def test_qa_oracle_stub_fallback(tmp_path, monkeypatch):
    """_compile_skill_stub writes a valid PlaybookSkill-compatible file."""
    monkeypatch.setenv("SELVA_SKILLS_DIR", str(tmp_path))

    from selva_workflows.acp_qa_oracle import ACPQAOracleNode

    node = ACPQAOracleNode(source_code="x = 1", test_suite="assert x == 1")
    path = node._compile_skill_stub("stub-run-xyz")

    assert os.path.isfile(path)
    with open(path) as f:
        text = f.read()
    assert "SKILL_DESCRIPTION" in text
    assert "SKILL_METADATA" in text
    assert "SKILL_ENTRYPOINT" in text


# ---------------------------------------------------------------------------
# HonchoProfiler — Dialectic User Modelling
# ---------------------------------------------------------------------------


def test_honcho_default_profile():
    """Without a memory store, the profiler returns the default profile."""
    from selva_workflows.honcho import HonchoProfiler

    profiler = HonchoProfiler(memory_store=None)
    profile = profiler.get_profile("alice")

    assert profile["verbosity"] == "concise"
    assert profile["review_strictness"] == "moderate"
    assert profile["defensive_assertions"] is True


def test_honcho_update_profile_reflects_in_addendum():
    """Updating a preference should appear in the generated system addendum."""
    from selva_workflows.honcho import HonchoProfiler

    profiler = HonchoProfiler(memory_store=None)
    profiler.update_profile("bob", "verbosity", "verbose")

    addendum = profiler.get_system_addendum("bob")
    assert "verbose" in addendum
    assert "bob" in addendum


def test_honcho_system_addendum_contains_all_fields():
    from selva_workflows.honcho import DEFAULT_PROFILE, HonchoProfiler

    profiler = HonchoProfiler(memory_store=None)
    addendum = profiler.get_system_addendum("carol")

    for key in ("verbosity", "code_style", "review_strictness", "preferred_language"):
        assert DEFAULT_PROFILE[key] in addendum, f"Expected {key} value in addendum"


# ---------------------------------------------------------------------------
# EdgeMemoryDB — insert_transcript
# ---------------------------------------------------------------------------


def test_edge_memory_insert_and_retrieve():
    """insert_transcript should be FTS-searchable after insertion."""
    from nexus_api.memory_store.db import EdgeMemoryDB

    db = EdgeMemoryDB(":memory:")
    db.insert_transcript(
        run_id="run-edge-001",
        agent_role="acp-qa-oracle",
        role="assistant",
        content="The captcha bypass logic has been successfully extracted.",
    )

    results = db.fts_search("bypass captcha")
    assert len(results) >= 1
    assert "captcha" in results[0]["content"].lower()
    db.close()
