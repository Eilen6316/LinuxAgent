"""Recorded-replay evaluation for the intent router prompt.

The replay path feeds recorded *real* model output through the live parser and
normalizer, so the routing logic is never mocked (R-TEST-02); only the network
call is replaced by a committed recording.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from ..graph.intent_router import (
    IntentDecision,
    _normalize_incidental_artifact_clarification,
    _parse_intent_decision,
)
from ..prompts_loader import find_prompts_dir

ROUTER_PROMPT_FILENAME = "intent_router.md"

# A deliberately static stand-in for the runtime router_context (which is built
# from live provider/model/tool data). Fixing it keeps recordings deterministic
# and reproducible; it is folded into prompt_fingerprint() so editing it forces a
# re-record.
ROUTER_CONTEXT_FIXTURE = (
    "LinuxAgent operating context (router view).\n"
    "LLM-visible tool names: read_file, list_directory, search_files, fetch_url."
)


@dataclass(frozen=True)
class GoldenCase:
    id: str
    input: str
    expected_mode: str
    expected_answer_context: str | None = None
    lang: str | None = None
    note: str = ""


@dataclass(frozen=True)
class Recording:
    id: str
    raw_response: str


def prompt_fingerprint() -> str:
    """SHA-256 of the live router prompt plus the fixed router context.

    The fixture is folded in so that changing ROUTER_CONTEXT_FIXTURE also
    invalidates recordings and forces a re-record.
    """
    text = (find_prompts_dir() / ROUTER_PROMPT_FILENAME).read_text(encoding="utf-8")
    payload = f"{text}\n--- router_context ---\n{ROUTER_CONTEXT_FIXTURE}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


MANIFEST_FILENAME = "manifest.json"


def load_recording(recordings_dir: Path, case_id: str) -> Recording | None:
    path = recordings_dir / f"{case_id}.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return Recording(id=str(payload["id"]), raw_response=str(payload["raw_response"]))


def load_manifest(recordings_dir: Path) -> dict[str, Any] | None:
    path = recordings_dir / MANIFEST_FILENAME
    if not path.is_file():
        return None
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A corrupt manifest is treated as missing so the staleness guard reports
        # the actionable "run `make eval-record`" message instead of a traceback.
        return None
    return parsed if isinstance(parsed, dict) else None


def load_golden_cases(path: Path) -> list[GoldenCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return [
        GoldenCase(
            id=str(item["id"]),
            input=str(item["input"]),
            expected_mode=str(item["expected_mode"]),
            expected_answer_context=(
                str(item["expected_answer_context"])
                if item.get("expected_answer_context") is not None
                else None
            ),
            lang=str(item["lang"]) if item.get("lang") is not None else None,
            note=str(item.get("note", "")),
        )
        for item in raw
    ]


def replay(case: GoldenCase, recording: Recording) -> IntentDecision:
    """Feed a recorded raw response through the live parser + normalizer.

    This exercises the same routing logic the runtime uses; nothing is mocked.
    Known delta: the runtime caps DIRECT_ANSWER ``parallel_tasks`` via
    ``parallel_direct_answer_tasks``; replay leaves it uncapped. No current
    golden case emits parallel_tasks, so add a ``max_parallel_tasks`` parameter
    here once one does.
    """
    decision = _parse_intent_decision(recording.raw_response)
    return _normalize_incidental_artifact_clarification(case.input, decision)


def assert_recordings_fresh(recordings_dir: Path) -> None:
    manifest = load_manifest(recordings_dir)
    assert manifest is not None, f"no manifest in {recordings_dir}; run `make eval-record`"
    recorded = manifest.get("prompt_fingerprint")
    current = prompt_fingerprint()
    assert recorded == current, (
        "recordings stale: intent_router.md changed since last recording; "
        "run `make eval-record` to refresh "
        f"(recorded={recorded!r}, current={current!r})"
    )


def iter_replayed(
    golden_path: Path, recordings_dir: Path
) -> Iterator[tuple[GoldenCase, IntentDecision | None, Recording | None]]:
    for case in load_golden_cases(golden_path):
        recording = load_recording(recordings_dir, case.id)
        decision = replay(case, recording) if recording is not None else None
        yield case, decision, recording
