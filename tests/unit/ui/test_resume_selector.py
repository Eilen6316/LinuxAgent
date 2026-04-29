"""Resume selector tests."""

from __future__ import annotations

from types import SimpleNamespace

from linuxagent.ui.resume_selector import ResumeSelector


def test_resume_selector_moves_with_visible_window() -> None:
    sessions = [
        SimpleNamespace(thread_id=f"thread-{index}", label=f"session {index}") for index in range(5)
    ]
    selector = ResumeSelector(sessions, max_visible=3)

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
