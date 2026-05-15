"""Command review helper tests."""

from __future__ import annotations

from linuxagent.command_review import command_review, numbered_lines


def test_command_review_extracts_inline_python_payload() -> None:
    review = command_review("python3 -c 'print(1)'")

    assert review.inline_payload_command == "python3"
    assert review.inline_payload_flag == "-c"
    assert review.inline_payload == "print(1)"
    assert review.inline_payload_truncated is False


def test_command_review_extracts_attached_node_payload() -> None:
    review = command_review("node -econsole.log(1)")

    assert review.inline_payload_command == "node"
    assert review.inline_payload_flag == "-e"
    assert review.inline_payload == "console.log(1)"


def test_command_review_truncates_long_command_and_payload() -> None:
    payload = "print(" + repr("x" * 2000) + ")"
    review = command_review(f"python3 -c {payload!r}")

    assert review.command_truncated is True
    assert "[truncated for review]" in review.command_display
    assert review.inline_payload is not None
    assert review.inline_payload_truncated is True
    assert "[truncated for review]" in review.inline_payload


def test_numbered_lines_formats_payload_for_review() -> None:
    assert numbered_lines("one\ntwo") == "1 | one\n2 | two"
