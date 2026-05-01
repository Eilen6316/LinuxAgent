"""Approval selector behavior tests."""

from __future__ import annotations

import pytest

from linuxagent.ui.approval_selector import ApprovalOption, ApprovalSelector


def _options() -> tuple[ApprovalOption, ...]:
    return (
        ApprovalOption("y", "yes", "接受 / Yes", "Allow once."),
        ApprovalOption("a", "yes_all", "接受，不再询问 / Yes, don't ask again", "Allow scope."),
        ApprovalOption("n", "no", "不接受 / No", "Deny."),
    )


def test_approval_selector_defaults_to_last_option() -> None:
    selector = ApprovalSelector(_options())

    assert selector.selected_decision() == "no"


def test_approval_selector_moves_and_clamps() -> None:
    selector = ApprovalSelector(_options())

    selector.move(-1)
    assert selector.selected_decision() == "yes_all"

    selector.move(-5)
    assert selector.selected_decision() == "yes"

    selector.move(99)
    assert selector.selected_decision() == "no"


def test_approval_selector_fragments_show_labels() -> None:
    selector = ApprovalSelector(_options(), default_index=0)

    rendered = "".join(str(fragment[1]) for fragment in selector._fragments())

    assert "Allow this operation?" in rendered
    assert "1. 接受 / Yes" in rendered
    assert "3. 不接受 / No" in rendered


def test_approval_selector_requires_options() -> None:
    with pytest.raises(ValueError, match="requires at least one option"):
        ApprovalSelector(())
