"""Display-only i18n tests for runbook metadata."""

from __future__ import annotations

from pathlib import Path

from linuxagent.config.models import LanguageCode
from linuxagent.graph.runbook_planning import build_runbook_guidance
from linuxagent.i18n import Translator
from linuxagent.runbooks import RunbookEngine, load_runbooks
from linuxagent.runbooks.display import runbook_display_title, runbook_step_display_purpose
from linuxagent.runbooks.models import Runbook, RunbookStep


def test_runbook_display_metadata_can_localize_without_changing_source_fields() -> None:
    runbook = Runbook(
        id="disk.quick",
        title="Disk quick check",
        title_i18n={LanguageCode.ZH_CN: "磁盘快速检查"},
        steps=(
            RunbookStep(
                command="df -h",
                purpose="Show filesystem usage",
                purpose_i18n={LanguageCode.ZH_CN: "显示文件系统使用情况"},
                read_only=True,
            ),
        ),
    )

    assert runbook.title == "Disk quick check"
    assert runbook.steps[0].purpose == "Show filesystem usage"
    assert runbook_display_title(runbook, Translator(LanguageCode.ZH_CN)) == "磁盘快速检查"
    assert (
        runbook_step_display_purpose(runbook.steps[0], Translator(LanguageCode.ZH_CN))
        == "显示文件系统使用情况"
    )
    assert runbook_display_title(runbook, Translator(LanguageCode.EN_US)) == "Disk quick check"


def test_builtin_runbook_display_metadata_is_available_but_guidance_stays_source_text() -> None:
    runbooks = load_runbooks(Path(__file__).resolve().parents[3] / "runbooks")
    disk = next(runbook for runbook in runbooks if runbook.id == "disk.full")
    guidance = build_runbook_guidance(RunbookEngine((disk,)))

    assert runbook_display_title(disk, Translator(LanguageCode.ZH_CN)) == "排查磁盘使用情况"
    assert "Investigate disk usage" in guidance
    assert "排查磁盘使用情况" not in guidance
    assert "Show filesystem usage" in guidance
    assert "显示文件系统使用情况" not in guidance
