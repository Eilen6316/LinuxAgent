"""Recording logic for the intent router eval (network lives in the CLI)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from ..interfaces import LLMProvider
from ..prompts_loader import build_intent_router_prompt
from .intent_router_eval import (
    MANIFEST_FILENAME,
    ROUTER_CONTEXT_FIXTURE,
    load_golden_cases,
    prompt_fingerprint,
)


async def record_intent_router(
    provider: LLMProvider,
    golden_path: Path,
    out_dir: Path,
    *,
    provider_name: str,
    model: str,
    recorded_at: str | None = None,
) -> int:
    """Call the live provider per golden case and write committed recordings.

    All filesystem writes happen after every provider call succeeds, so a
    mid-run failure leaves no partial recordings on disk. Returns the number of
    cases recorded.
    """
    prompt = build_intent_router_prompt()
    cases = load_golden_cases(golden_path)
    recordings: list[tuple[str, str]] = []
    for case in cases:
        messages = prompt.format_messages(
            chat_history=[],
            product_context=ROUTER_CONTEXT_FIXTURE,
            user_input=case.input,
        )
        raw = (await provider.complete(messages)).strip()
        recordings.append((case.id, raw))
    manifest = {
        "prompt_fingerprint": prompt_fingerprint(),
        "provider": provider_name,
        "model": model,
        "recorded_at": recorded_at,
        "case_count": len(cases),
    }
    _write_recordings(out_dir, recordings, manifest)
    return len(cases)


def _write_recordings(
    out_dir: Path, recordings: list[tuple[str, str]], manifest: Mapping[str, object]
) -> None:
    """Persist recordings and manifest to ``out_dir`` (synchronous I/O)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for case_id, raw in recordings:
        (out_dir / f"{case_id}.json").write_text(
            json.dumps({"id": case_id, "raw_response": raw}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    (out_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
