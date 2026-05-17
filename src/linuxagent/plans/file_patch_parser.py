"""FilePatchPlan JSON parsing helpers."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import ValidationError

from .file_patch_models import FilePatchPlan, FilePatchPlanParseError


def parse_file_patch_plan(text: str) -> FilePatchPlan:
    payload = _extract_json_payload(text)
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise FilePatchPlanParseError(f"LLM response is not valid JSON: {exc.msg}") from exc
    if not isinstance(raw, dict):
        raise FilePatchPlanParseError("LLM response JSON must be an object")
    if "unified_diff" not in raw and raw.get("plan_type") != "file_patch":
        raise FilePatchPlanParseError("LLM response is not a FilePatchPlan object")
    try:
        return FilePatchPlan.model_validate(raw)
    except ValidationError as exc:
        raise FilePatchPlanParseError(_format_validation_error(exc)) from exc


def file_patch_plan_json(
    path: str,
    body: str,
    *,
    goal: str = "Apply file patch",
    request_intent: Literal["create", "update", "unknown"] = "create",
) -> str:
    line_count = len(body.splitlines())
    diff_lines = ["--- /dev/null", f"+++ {path}", f"@@ -0,0 +1,{line_count} @@"]
    diff_lines.extend(f"+{line}" for line in body.splitlines())
    payload: dict[str, Any] = {
        "plan_type": "file_patch",
        "goal": goal,
        "request_intent": request_intent,
        "files_changed": [path],
        "unified_diff": "\n".join(diff_lines) + "\n",
        "risk_summary": "Creates or updates local files after confirmation.",
        "verification_commands": [],
        "permission_changes": [],
        "rollback_diff": "",
        "expected_side_effects": ["filesystem.write"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _extract_json_payload(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("{"):
        return stripped
    match = re.fullmatch(r"```(?:json)?\s*(\{.*\})\s*```", stripped, flags=re.DOTALL)
    if match is None:
        raise FilePatchPlanParseError("LLM response must be a JSON FilePatchPlan object")
    return match.group(1)


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        parts.append(f"{loc}: {err['msg']} (input={err.get('input')!r})")
    return "invalid FilePatchPlan: " + "; ".join(parts)
