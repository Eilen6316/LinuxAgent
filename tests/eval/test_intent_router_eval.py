"""Recorded-replay evaluation for the intent router prompt."""

from __future__ import annotations

import json
from pathlib import Path

from linuxagent.eval.intent_router_eval import (
    GoldenCase,
    load_golden_cases,
    load_manifest,
    load_recording,
    prompt_fingerprint,
)


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


def test_load_recording_reads_raw_response(tmp_path: Path) -> None:
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    (rec_dir / "cap.json").write_text(
        json.dumps({"id": "cap", "raw_response": '{"mode":"DIRECT_ANSWER"}'}),
        encoding="utf-8",
    )

    recording = load_recording(rec_dir, "cap")

    assert recording is not None
    assert recording.id == "cap"
    assert recording.raw_response == '{"mode":"DIRECT_ANSWER"}'


def test_load_recording_missing_returns_none(tmp_path: Path) -> None:
    assert load_recording(tmp_path, "absent") is None


def test_load_manifest_missing_returns_none(tmp_path: Path) -> None:
    assert load_manifest(tmp_path) is None


def test_load_manifest_reads_fingerprint(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"prompt_fingerprint": "abc", "provider": "deepseek", "model": "x"}),
        encoding="utf-8",
    )

    manifest = load_manifest(tmp_path)

    assert manifest is not None
    assert manifest["prompt_fingerprint"] == "abc"


def test_prompt_fingerprint_is_stable_hex_and_tracks_router_prompt() -> None:
    from linuxagent.prompts_loader import find_prompts_dir

    fp = prompt_fingerprint()

    # 64 位十六进制 sha256，且对当前 intent_router.md 内容稳定
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)
    assert fp == prompt_fingerprint()
    assert (find_prompts_dir() / "intent_router.md").is_file()
