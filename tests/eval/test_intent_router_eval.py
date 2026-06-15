"""Recorded-replay evaluation for the intent router prompt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from linuxagent.eval.intent_router_eval import (
    GoldenCase,
    Recording,
    assert_recordings_fresh,
    iter_replayed,
    load_golden_cases,
    load_manifest,
    load_recording,
    prompt_fingerprint,
    replay,
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


def test_replay_returns_decision_from_recorded_json() -> None:
    case = GoldenCase(id="cap", input="你都能干啥啊", expected_mode="DIRECT_ANSWER")
    recording = Recording(
        id="cap",
        raw_response='{"mode":"DIRECT_ANSWER","answer_context":"self_manual","answer":"","reason":"x"}',
    )

    decision = replay(case, recording)

    assert decision.mode.value == "DIRECT_ANSWER"
    assert decision.answer_context.value == "self_manual"


def test_replay_applies_incidental_artifact_normalization() -> None:
    # router 录制返回的是"问增量路径"的 CLARIFY，归一化应转为 COMMAND_PLAN
    case = GoldenCase(
        id="incidental",
        input="随便写一个脚本吧 测试一下你的能力",
        expected_mode="COMMAND_PLAN",
    )
    recording = Recording(
        id="incidental",
        raw_response='{"mode":"CLARIFY","answer":"你想把脚本保存到哪个路径或文件名？","reason":"missing path"}',
    )

    decision = replay(case, recording)

    assert decision.mode.value == "COMMAND_PLAN"


def test_prompt_fingerprint_is_stable_hex_and_tracks_router_prompt() -> None:
    from linuxagent.prompts_loader import find_prompts_dir

    fp = prompt_fingerprint()

    # 64 位十六进制 sha256，且对当前 intent_router.md 内容稳定
    assert len(fp) == 64
    assert all(c in "0123456789abcdef" for c in fp)
    assert fp == prompt_fingerprint()
    assert (find_prompts_dir() / "intent_router.md").is_file()


def test_assert_recordings_fresh_passes_on_matching_fingerprint(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"prompt_fingerprint": prompt_fingerprint()}), encoding="utf-8"
    )
    # 不抛即通过
    assert_recordings_fresh(tmp_path)


def test_assert_recordings_fresh_fails_when_stale(tmp_path: Path) -> None:
    (tmp_path / "manifest.json").write_text(
        json.dumps({"prompt_fingerprint": "stale"}), encoding="utf-8"
    )
    with pytest.raises(AssertionError, match="make eval-record"):
        assert_recordings_fresh(tmp_path)


def test_assert_recordings_fresh_fails_when_manifest_missing(tmp_path: Path) -> None:
    with pytest.raises(AssertionError, match="no manifest"):
        assert_recordings_fresh(tmp_path)


def test_iter_replayed_matches_synthetic_recordings(tmp_path: Path) -> None:
    golden = tmp_path / "golden.yaml"
    golden.write_text(
        "- id: cap\n"
        '  input: "你都能干啥啊"\n'
        "  expected_mode: DIRECT_ANSWER\n"
        "  expected_answer_context: self_manual\n",
        encoding="utf-8",
    )
    rec_dir = tmp_path / "recordings"
    rec_dir.mkdir()
    (rec_dir / "cap.json").write_text(
        json.dumps(
            {
                "id": "cap",
                "raw_response": '{"mode":"DIRECT_ANSWER","answer_context":"self_manual","answer":"","reason":"x"}',
            }
        ),
        encoding="utf-8",
    )

    results = list(iter_replayed(golden, rec_dir))

    assert len(results) == 1
    case, decision, recording = results[0]
    assert case.id == "cap"
    assert recording is not None
    assert decision.mode.value == case.expected_mode
    assert decision.answer_context.value == case.expected_answer_context


_REPO_ROOT = Path(__file__).resolve().parents[2]
_GOLDEN = _REPO_ROOT / "tests/eval/golden/intent_router.yaml"
_RECORDINGS = _REPO_ROOT / "tests/eval/recordings/intent_router"


def test_live_golden_recordings_are_fresh() -> None:
    if load_manifest(_RECORDINGS) is None:
        pytest.skip("no recordings yet; run `make eval-record`")
    assert_recordings_fresh(_RECORDINGS)


def _golden_ids() -> list[str]:
    if not _GOLDEN.is_file():
        return []
    return [case.id for case in load_golden_cases(_GOLDEN)]


@pytest.mark.parametrize("case_id", _golden_ids())
def test_live_golden_case_routes_as_expected(case_id: str) -> None:
    case = next(c for c in load_golden_cases(_GOLDEN) if c.id == case_id)
    recording = load_recording(_RECORDINGS, case.id)
    if recording is None:
        pytest.skip(f"no recording for {case.id!r}; run `make eval-record`")
    decision = replay(case, recording)
    assert (
        decision.mode.value == case.expected_mode
    ), f"{case.id}: expected {case.expected_mode}, got {decision.mode.value}"
    if case.expected_answer_context is not None:
        assert decision.answer_context.value == case.expected_answer_context, (
            f"{case.id}: answer_context expected {case.expected_answer_context}, "
            f"got {decision.answer_context.value}"
        )
