"""
Tests for Gap 5: agentskills.io Registry Compatibility.

Verifies:
- LLM-compiled skills include SKILL_SCHEMA_VERSION = "agentskills/v1"
- Registry warns on legacy skills missing the schema field
- Skills with correct v1 schema load without warnings
"""

from __future__ import annotations

import logging
import textwrap
from pathlib import Path

import pytest

V1_SKILL = textwrap.dedent("""\
    SKILL_SCHEMA_VERSION = "agentskills/v1"
    SKILL_VERSION = "1.0.0"
    SKILL_AUTHOR = "selva-qa-oracle"
    SKILL_TAGS = ["web", "scraping"]
    SKILL_DESCRIPTION = "Scrapes product data from a public catalogue API."
    SKILL_METADATA = {"run_id": "run-v1-001", "last_validated": "2026-04-13T00:00:00+00:00"}

    def SKILL_ENTRYPOINT(*args, **kwargs):
        return {"product_count": 42}
""")

LEGACY_SKILL = textwrap.dedent("""\
    SKILL_DESCRIPTION = "Old skill without schema version."
    SKILL_METADATA = {"run_id": "legacy-run"}

    def SKILL_ENTRYPOINT(*args, **kwargs):
        return "legacy result"
""")


@pytest.fixture()
def skills_dir(tmp_path: Path) -> Path:
    return tmp_path


class TestRegistryV1Compliance:
    def test_v1_skill_loads_cleanly(self, skills_dir, caplog):
        (skills_dir / "v1_skill.py").write_text(V1_SKILL)

        from selva_skills.registry import SkillRegistry

        reg = SkillRegistry(skills_dir=str(skills_dir))

        with caplog.at_level(logging.WARNING, logger="selva_skills.registry"):
            reg.load_skills()

        assert "v1_skill" in reg.skills
        assert "missing SKILL_SCHEMA_VERSION" not in caplog.text

    def test_legacy_skill_warns(self, skills_dir, caplog):
        (skills_dir / "legacy_skill.py").write_text(LEGACY_SKILL)

        from selva_skills.registry import SkillRegistry

        reg = SkillRegistry(skills_dir=str(skills_dir))

        with caplog.at_level(logging.WARNING, logger="selva_skills.registry"):
            reg.load_skills()

        assert "legacy_skill" in reg.skills
        assert "missing SKILL_SCHEMA_VERSION" in caplog.text

    def test_list_skills_returns_descriptions(self, skills_dir):
        (skills_dir / "v1_skill.py").write_text(V1_SKILL)

        from selva_skills.registry import SkillRegistry

        reg = SkillRegistry(skills_dir=str(skills_dir))
        reg.load_skills()

        listing = reg.list_skills()
        assert "v1_skill" in listing
        assert "catalogue" in listing["v1_skill"].lower()


class TestQAOracleV1Synthesis:
    def test_synthesis_prompt_mandates_schema_version(self, tmp_path, monkeypatch):
        """The SKILL_SYNTHESIS_PROMPT should require SKILL_SCHEMA_VERSION = 'agentskills/v1'."""
        from selva_workflows.acp_qa_oracle import SKILL_SYNTHESIS_PROMPT

        assert "agentskills/v1" in SKILL_SYNTHESIS_PROMPT
        assert "SKILL_SCHEMA_VERSION" in SKILL_SYNTHESIS_PROMPT
        assert "SKILL_VERSION" in SKILL_SYNTHESIS_PROMPT
        assert "SKILL_AUTHOR" in SKILL_SYNTHESIS_PROMPT
        assert "SKILL_TAGS" in SKILL_SYNTHESIS_PROMPT

    def test_stub_fallback_includes_run_id(self, tmp_path, monkeypatch):
        """Stub compiler should at minimum embed the run_id in SKILL_METADATA."""
        monkeypatch.setenv("SELVA_SKILLS_DIR", str(tmp_path))

        from selva_workflows.acp_qa_oracle import ACPQAOracleNode

        node = ACPQAOracleNode(source_code="x = 1", test_suite="")
        path = node._compile_skill_stub("run-v1-check")

        with open(path) as f:
            content = f.read()
        assert "run-v1-check" in content
        assert "SKILL_ENTRYPOINT" in content
