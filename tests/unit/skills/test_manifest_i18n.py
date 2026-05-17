"""Display-only i18n tests for Skill manifests."""

from __future__ import annotations

from linuxagent.config.models import LanguageCode
from linuxagent.i18n import Translator
from linuxagent.skills.display import skill_display_description
from linuxagent.skills.manifest import SkillManifest, skill_planner_guidance


def test_skill_description_i18n_is_display_only() -> None:
    manifest = SkillManifest(
        name="disk-pack",
        version="1.0",
        description="Disk guidance",
        description_i18n={LanguageCode.ZH_CN: "磁盘指导"},
        planner_guidance="Prefer df before du.",
    )

    assert manifest.description == "Disk guidance"
    assert skill_display_description(manifest, Translator(LanguageCode.ZH_CN)) == "磁盘指导"
    assert skill_display_description(manifest, Translator(LanguageCode.EN_US)) == "Disk guidance"
    assert skill_planner_guidance((manifest,)) == (
        "Skill guidance from disk-pack@1.0 (advisory only):\nPrefer df before du.",
    )
