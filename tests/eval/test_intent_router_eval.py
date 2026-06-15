"""Recorded-replay evaluation for the intent router prompt."""

from __future__ import annotations

from pathlib import Path

from linuxagent.eval.intent_router_eval import GoldenCase, load_golden_cases


def test_load_golden_cases_parses_fields(tmp_path: Path) -> None:
    golden = tmp_path / "g.yaml"
    golden.write_text(
        "- id: cap\n"
        '  input: "你都能干啥啊"\n'
        "  expected_mode: DIRECT_ANSWER\n"
        "  expected_answer_context: self_manual\n"
        "  lang: zh\n"
        "  note: capability question\n",
        encoding="utf-8",
    )

    cases = load_golden_cases(golden)

    assert cases == [
        GoldenCase(
            id="cap",
            input="你都能干啥啊",
            expected_mode="DIRECT_ANSWER",
            expected_answer_context="self_manual",
            lang="zh",
            note="capability question",
        )
    ]


def test_load_golden_cases_defaults_optional_fields(tmp_path: Path) -> None:
    golden = tmp_path / "g.yaml"
    golden.write_text(
        "- id: probe\n" '  input: "现在有哪些进程"\n' "  expected_mode: COMMAND_PLAN\n",
        encoding="utf-8",
    )

    case = load_golden_cases(golden)[0]

    assert case.expected_answer_context is None
    assert case.lang is None
    assert case.note == ""
