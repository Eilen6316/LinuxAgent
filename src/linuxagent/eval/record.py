"""Recording logic for the intent router eval (network lives in the CLI)."""

from __future__ import annotations

import json
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

    Returns the number of cases recorded.
    """
    prompt = build_intent_router_prompt()
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = load_golden_cases(golden_path)
    for case in cases:
        messages = prompt.format_messages(
            chat_history=[],
            product_context=ROUTER_CONTEXT_FIXTURE,
            user_input=case.input,
        )
        raw = (await provider.complete(messages)).strip()
        (out_dir / f"{case.id}.json").write_text(
            json.dumps({"id": case.id, "raw_response": raw}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    manifest = {
        "prompt_fingerprint": prompt_fingerprint(),
        "provider": provider_name,
        "model": model,
        "recorded_at": recorded_at,
        "case_count": len(cases),
    }
    (out_dir / MANIFEST_FILENAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return len(cases)
