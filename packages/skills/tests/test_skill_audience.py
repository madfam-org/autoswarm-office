"""Tests for the skill-level audience split (phase 3).

Covers:
- Default ``SkillMetadata.audience`` is TENANT
- ``list_skills(audience=...)`` filters platform skills for tenant callers
- ``activate(name, audience=...)`` raises ``SkillAudienceMismatch`` when
  a tenant swarm tries to load a platform-audience skill
- Regression: known-platform skills (cluster-triage, dns-migration,
  incident-triage, staging-refresh, tenant-onboarding, skill-creator,
  mcp-builder) are all tagged platform and hidden from tenant audience
"""

from __future__ import annotations

import pytest

# Enable enforcement for all tests in this module.
pytestmark = pytest.mark.usefixtures("_audience_enforce_on")


@pytest.fixture
def _audience_enforce_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUDIENCE_FILTER_ENABLED", "true")


from selva_skills import SkillAudience, SkillMetadata, get_skill_registry  # noqa: E402
from selva_skills.registry import SkillAudienceMismatch  # noqa: E402

# Skills that MUST be tagged platform. Belt-and-braces regression test.
PLATFORM_SKILLS: frozenset[str] = frozenset(
    {
        "cluster-triage",
        "dns-migration",
        "incident-triage",
        "staging-refresh",
        "tenant-onboarding",
        "skill-creator",
        "mcp-builder",
        "vault-break-glass",
    }
)


class TestSkillMetadataDefault:
    def test_default_audience_is_tenant(self) -> None:
        m = SkillMetadata(name="example-skill", description="irrelevant")
        assert m.audience is SkillAudience.TENANT


class TestRegistryFilter:
    def test_list_skills_unfiltered(self) -> None:
        reg = get_skill_registry()
        names = {s.name for s in reg.list_skills()}
        assert PLATFORM_SKILLS.issubset(names)

    def test_tenant_audience_hides_platform_skills(self) -> None:
        reg = get_skill_registry()
        tenant_visible = {s.name for s in reg.list_skills(audience=SkillAudience.TENANT)}
        leaked = tenant_visible & PLATFORM_SKILLS
        assert not leaked, f"Platform skills visible to tenant audience: {leaked}"

    def test_platform_audience_sees_all_skills(self) -> None:
        reg = get_skill_registry()
        all_names = {s.name for s in reg.list_skills()}
        platform_names = {s.name for s in reg.list_skills(audience=SkillAudience.PLATFORM)}
        assert all_names == platform_names


class TestPlatformSkillTagging:
    @pytest.mark.parametrize("name", sorted(PLATFORM_SKILLS))
    def test_skill_is_tagged_platform(self, name: str) -> None:
        reg = get_skill_registry()
        meta = reg.get_metadata(name)
        assert meta is not None, f"skill {name!r} not discovered"
        assert meta.audience is SkillAudience.PLATFORM, (
            f"skill {name!r} must be audience=platform but is {meta.audience}"
        )


class TestActivateGuard:
    def test_platform_skill_activates_for_platform_audience(self) -> None:
        reg = get_skill_registry()
        defn = reg.activate("cluster-triage", audience=SkillAudience.PLATFORM)
        assert defn.meta.name == "cluster-triage"

    def test_platform_skill_raises_for_tenant_audience(self) -> None:
        reg = get_skill_registry()
        with pytest.raises(SkillAudienceMismatch):
            reg.activate("cluster-triage", audience=SkillAudience.TENANT)

    def test_tenant_skill_activates_for_tenant_audience(self) -> None:
        reg = get_skill_registry()
        defn = reg.activate("outbound-voice", audience=SkillAudience.TENANT)
        assert defn.meta.name == "outbound-voice"

    def test_tenant_skill_activates_for_platform_audience(self) -> None:
        reg = get_skill_registry()
        # Platform is superset — can activate tenant skills too
        defn = reg.activate("outbound-voice", audience=SkillAudience.PLATFORM)
        assert defn.meta.name == "outbound-voice"

    def test_activate_without_audience_is_permissive(self) -> None:
        # Backward compat: existing callers that don't pass audience are
        # not affected by the new guard.
        reg = get_skill_registry()
        defn = reg.activate("cluster-triage")
        assert defn.meta.name == "cluster-triage"
