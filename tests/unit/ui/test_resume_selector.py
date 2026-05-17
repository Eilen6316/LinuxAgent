"""Resume selector tests."""

from __future__ import annotations

from types import SimpleNamespace

from linuxagent.config.models import LanguageCode
from linuxagent.i18n import Translator
from linuxagent.ui.resume_selector import ResumeSelector


def test_resume_selector_moves_with_visible_window() -> None:
    sessions = [
        SimpleNamespace(thread_id=f"thread-{index}", label=f"session {index}") for index in range(5)
    ]
    selector = ResumeSelector(
        sessions,
        max_visible=3,
        translator=Translator(LanguageCode.EN_US),
    )

    selector.move(4)

    assert selector.selected_thread_id() == "thread-4"
    rendered = "".join(fragment[1] for fragment in selector._fragments())
    assert "session 2" in rendered
    assert "session 4" in rendered
    assert "Showing 3-5 of 5 sessions" in rendered


def test_resume_selector_enter_result_tracks_selected_thread() -> None:
    sessions = [
        SimpleNamespace(thread_id="older", label="older session"),
        SimpleNamespace(thread_id="newer", label="newer session"),
    ]
    selector = ResumeSelector(sessions)

    selector.move(1)

    assert selector.selected_thread_id() == "newer"


def test_resume_selector_uses_label_not_dataclass_repr() -> None:
    session = SimpleNamespace(thread_id="saved", label="22:48 修改 /tmp/disk_info.sh")
    selector = ResumeSelector([session])

    rendered = "".join(fragment[1] for fragment in selector._fragments())

    assert "22:48 修改 /tmp/disk_info.sh" in rendered
    assert "namespace(" not in rendered


def test_resume_selector_handles_empty_sessions() -> None:
    selector = ResumeSelector(
        [],
        max_visible=3,
        translator=Translator(LanguageCode.EN_US),
    )

    selector.move(1)
    selector.page(1)
    selector.first()
    selector.last()

    assert selector.selected_thread_id() is None
    rendered = "".join(fragment[1] for fragment in selector._fragments())
    assert "Resume session" in rendered


def test_resume_selector_default_title_is_chinese() -> None:
    selector = ResumeSelector([], max_visible=3)

    rendered = "".join(fragment[1] for fragment in selector._fragments())

    assert "恢复会话" in rendered


def test_resume_selector_pages_and_home_end() -> None:
    sessions = [
        SimpleNamespace(thread_id=f"thread-{index}", label=f"session {index}") for index in range(8)
    ]
    selector = ResumeSelector(sessions, max_visible=3)

    selector.page(1)
    assert selector.selected_thread_id() == "thread-3"
    selector.last()
    assert selector.selected_thread_id() == "thread-7"
    selector.first()
    assert selector.selected_thread_id() == "thread-0"
