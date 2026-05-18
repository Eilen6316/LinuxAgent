"""Runtime event messages shown by the CLI UI."""

from __future__ import annotations

import json
from typing import Any

from ..i18n import CatalogError, Translator, default_translator
from ..security.redaction import redact_text

_TOOL_EVIDENCE_ITEMS = 3
_READ_FILE_HEAD_EVIDENCE_ITEMS = 2
_READ_FILE_TAIL_EVIDENCE_ITEMS = 3
_TOOL_EVIDENCE_CHARS = 180
_TOOL_ERROR_CHARS = 220
_WORKER_ITEMS = 6
_WORKER_DETAIL_CHARS = 120


def tool_event_message(event: dict[str, Any], translator: Translator | None = None) -> str | None:
    tr = translator or default_translator()
    phase = str(event.get("phase") or "")
    tool_name = str(event.get("tool_name") or "")
    raw_args = event.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    if phase == "start":
        return _tool_start_message(tool_name, args, tr)
    if phase == "error":
        return _tool_error_message(tool_name, args, event, tr)
    if phase == "end":
        return _tool_end_message(tool_name, args, event, tr)
    return None


def tool_activity_message(
    event: dict[str, Any], translator: Translator | None = None
) -> str | None:
    tr = translator or default_translator()
    phase = str(event.get("phase") or "")
    tool_name = str(event.get("tool_name") or "")
    raw_args = event.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    if phase == "start":
        return _tool_start_message(tool_name, args, tr)
    if phase == "error":
        return _tool_activity_error(tool_name, args, event, tr)
    if phase == "end":
        return _tool_activity_end(tool_name, args, event, tr)
    return None


def command_event_key(event: dict[str, Any]) -> tuple[str, str]:
    return (str(event.get("trace_id") or ""), str(event.get("command") or ""))


def runtime_event_message(
    event: dict[str, Any], translator: Translator | None = None
) -> str | None:
    tr = translator or default_translator()
    event_type = str(event.get("type") or "")
    phase = str(event.get("phase") or "")
    if event_type == "command":
        return _command_event_message(phase, event, tr)
    if event_type == "command_batch":
        return _command_batch_event_message(phase, event, tr)
    if event_type in {"worker_group", "agent_group"}:
        return _worker_group_event_message(event, tr)
    if event_type == "background_job":
        return _background_job_event_message(phase, event, tr)
    if event_type == "activity":
        return _activity_event_message(phase, tr)
    return None


def _command_event_message(phase: str, event: dict[str, Any], translator: Translator) -> str | None:
    command = str(event.get("command") or "")
    if phase == "start":
        return translator.t("runtime.command_start", command=command)
    if phase == "finish":
        return translator.t("runtime.command_finish", exit_code=event.get("exit_code"))
    return None


def _command_batch_event_message(
    phase: str, event: dict[str, Any], translator: Translator
) -> str | None:
    count = int(event.get("count") or 0)
    if phase == "start":
        return translator.t("runtime.batch_start", count=count)
    if phase == "finish":
        return translator.t("runtime.batch_finish", count=count)
    return None


def _worker_group_event_message(event: dict[str, Any], translator: Translator) -> str | None:
    title = _worker_group_title(event, translator)
    items = _worker_items(event)
    if not items:
        return title
    lines = [title]
    for item in items[:_WORKER_ITEMS]:
        name = _trim_agent_detail(
            _localized_event_text(item, translator, "name").strip()
            or str(item.get("id") or "worker")
        )
        status = _trim_agent_detail(_worker_status_text(item, translator))
        detail = _worker_detail(item, translator)
        suffix = f" - {detail}" if detail else ""
        lines.append(f"  - {name}: {status}{suffix}")
    remaining = len(items) - _WORKER_ITEMS
    if remaining > 0:
        lines.append(f"  - {translator.t('runtime.agent_group_more', count=remaining)}")
    return "\n".join(lines)


def _worker_group_title(event: dict[str, Any], translator: Translator) -> str:
    label = _localized_event_text(event, translator, "label").strip()
    active = int(event.get("active") or 0)
    total = int(event.get("total") or event.get("count") or active or len(_worker_items(event)))
    if label:
        return translator.t(
            "runtime.agent_group_status_named", label=label, active=active, total=total
        )
    return translator.t("runtime.agent_group_status", active=active, total=total)


def _worker_items(event: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    workers = _event_items(event.get("workers"))
    if workers:
        return workers
    return _event_items(event.get("agents"))


def _event_items(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, dict))


def _worker_status_text(item: dict[str, Any], translator: Translator) -> str:
    text = _localized_event_key_text(item, translator, "status").strip()
    if text:
        return text
    status = str(item.get("status") or "running")
    status_key = f"runtime.agent.status.{status}"
    try:
        return translator.t(status_key)
    except CatalogError:
        return status


def _worker_detail(item: dict[str, Any], translator: Translator) -> str:
    raw = (
        _localized_event_text(item, translator, "detail").strip()
        or _localized_event_text(item, translator, "summary").strip()
        or _localized_event_text(item, translator, "error").strip()
        or str(item.get("content") or "")
    )
    text = redact_text(str(raw)).text.strip()
    return _trim_agent_detail(" ".join(text.split()))


def _localized_event_text(item: dict[str, Any], translator: Translator, field: str) -> str:
    text = _localized_event_key_text(item, translator, field)
    if text:
        return text
    return str(item.get(field) or "")


def _localized_event_key_text(item: dict[str, Any], translator: Translator, field: str) -> str:
    key = item.get(f"{field}_key")
    if isinstance(key, str) and key.strip():
        params = item.get(f"{field}_params")
        if isinstance(params, dict):
            return translator.t(key, **params)
        return translator.t(key)
    return ""


def _trim_agent_detail(text: str) -> str:
    if len(text) <= _WORKER_DETAIL_CHARS:
        return text
    return text[: _WORKER_DETAIL_CHARS - 1].rstrip() + "…"


def _background_job_event_message(
    phase: str, event: dict[str, Any], translator: Translator
) -> str | None:
    job_id = str(event.get("job_id") or "")
    status = str(event.get("status") or "")
    if phase == "start":
        return translator.t("runtime.background_start", job_id=job_id)
    if phase == "finish":
        return translator.t("runtime.background_finish", job_id=job_id, status=status)
    return None


def _activity_event_message(phase: str, translator: Translator) -> str | None:
    labels = {
        "classify": translator.t("runtime.activity.classify"),
        "plan": translator.t("runtime.activity.plan"),
        "policy": translator.t("runtime.activity.policy"),
        "waiting_confirm": translator.t("runtime.activity.waiting_confirm"),
        "repair_plan": translator.t("runtime.activity.repair_plan"),
        "analyze": translator.t("runtime.activity.analyze"),
    }
    return labels.get(phase)


def _tool_start_message(tool_name: str, args: dict[str, Any], translator: Translator) -> str:
    if tool_name == "discover_project_guidance":
        return translator.t(
            "runtime.tool.start_discover_project_guidance",
            path=args.get("path") or ".",
        )
    if tool_name == "read_file":
        return translator.t("runtime.tool.start_read_file", path=args.get("path") or "").strip()
    if tool_name == "list_dir":
        return translator.t("runtime.tool.start_list_dir", path=args.get("path") or ".")
    if tool_name == "search_files":
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return translator.t("runtime.tool.start_search_files", root=root, pattern=pattern)
    if tool_name == "repair_file_patch":
        files = args.get("files") if isinstance(args.get("files"), list) else []
        suffix = f" {', '.join(str(item) for item in files)}" if files else ""
        return translator.t("runtime.tool.start_repair_file_patch", suffix=suffix)
    if tool_name == "fetch_url":
        return translator.t("runtime.tool.start_fetch_url", url=args.get("url") or "")
    return translator.t("runtime.tool.start_default", tool_name=tool_name)


def _tool_error_message(
    tool_name: str, args: dict[str, Any], event: dict[str, Any], translator: Translator
) -> str:
    target = _tool_target(tool_name, args)
    reason = _human_tool_error(event.get("output_preview") or event.get("output_text"), translator)
    location = f" {target}" if target else ""
    return translator.t("runtime.tool.error", tool_name=tool_name, location=location, reason=reason)


def _tool_target(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "search_files":
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return f"{root}: {pattern}".strip()
    if tool_name == "discover_project_guidance":
        target = args.get("path") or "."
        return str(target)
    target = args.get("path")
    if isinstance(target, str) and target:
        return target
    url = args.get("url")
    if isinstance(url, str) and url:
        return url
    return ""


def _human_tool_error(raw: Any, translator: Translator | None = None) -> str:
    tr = translator or default_translator()
    text = str(raw or "").strip()
    if not text:
        return tr.t("runtime.tool.unknown_error")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return _trim_tool_error(text)
    if not isinstance(payload, dict):
        return _trim_tool_error(text)
    message = payload.get("message")
    error_type = payload.get("error_type")
    if isinstance(message, str) and message.strip():
        reason = message.strip()
        if isinstance(error_type, str) and error_type and error_type not in reason:
            reason = f"{error_type}: {reason}"
        return _trim_tool_error(reason)
    status = payload.get("status")
    if isinstance(error_type, str) and error_type:
        return _trim_tool_error(error_type)
    if isinstance(status, str) and status:
        return _trim_tool_error(status)
    return _trim_tool_error(text)


def _trim_tool_error(text: str) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= _TOOL_ERROR_CHARS:
        return normalized
    return normalized[: _TOOL_ERROR_CHARS - 1].rstrip() + "…"


def _tool_end_message(
    tool_name: str, args: dict[str, Any], event: dict[str, Any], translator: Translator
) -> str | None:
    status = str(event.get("status") or "")
    if status not in {"allowed", "truncated"}:
        return None
    output = str(event.get("output_text") or event.get("output_preview") or "")
    suffix = (
        translator.t("runtime.tool.truncated_suffix")
        if status == "truncated" or event.get("truncated")
        else ""
    )
    if tool_name == "read_file":
        evidence = _read_file_evidence_summary(output, translator)
        heading = translator.t("runtime.tool.read_done", path=args.get("path") or "", suffix=suffix)
        return _tool_evidence_message(heading.strip(), evidence, translator)
    if tool_name == "discover_project_guidance":
        return _guidance_tool_end_message(args, output, suffix, translator)
    if tool_name == "list_dir":
        return _list_tool_end_message(args, output, suffix, translator)
    if tool_name == "search_files":
        return _search_tool_end_message(args, output, suffix, translator)
    if tool_name == "fetch_url":
        evidence = _tool_evidence_summary(output, translator)
        return _tool_evidence_message(
            translator.t("runtime.tool.fetch_done", url=args.get("url") or "", suffix=suffix),
            evidence,
            translator,
        )
    return None


def _guidance_tool_end_message(
    args: dict[str, Any], output: str, suffix: str, translator: Translator
) -> str:
    return _tool_evidence_message(
        translator.t(
            "runtime.tool.discover_project_guidance_done",
            path=args.get("path") or ".",
            suffix=suffix,
        ),
        _guidance_evidence_summary(output, translator),
        translator,
    )


def _list_tool_end_message(
    args: dict[str, Any], output: str, suffix: str, translator: Translator
) -> str:
    return _tool_evidence_message(
        translator.t("runtime.tool.list_done", path=args.get("path") or ".", suffix=suffix),
        _tool_evidence_summary(output, translator),
        translator,
    )


def _search_tool_end_message(
    args: dict[str, Any], output: str, suffix: str, translator: Translator
) -> str:
    root = args.get("root") or "."
    pattern = args.get("pattern") or ""
    return _tool_evidence_message(
        translator.t("runtime.tool.search_done", root=root, pattern=pattern, suffix=suffix),
        _tool_evidence_summary(output, translator),
        translator,
    )


def _tool_evidence_message(heading: str, evidence: tuple[str, ...], translator: Translator) -> str:
    bullets = "\n".join(f"  - {item}" for item in evidence)
    return f"{heading}\n  {translator.t('runtime.tool.evidence_preview')}\n{bullets}"


def _tool_activity_error(
    tool_name: str, args: dict[str, Any], event: dict[str, Any], translator: Translator
) -> str:
    status = str(event.get("status") or "error")
    target = _tool_target(tool_name, args)
    label = f"{tool_name} {target}".strip()
    return _tool_activity_summary(
        translator.t("runtime.tool.activity_status"), f"{label} · {status}"
    )


def _tool_activity_end(
    tool_name: str, args: dict[str, Any], event: dict[str, Any], translator: Translator
) -> str | None:
    status = str(event.get("status") or "")
    if status not in {"allowed", "truncated"}:
        return None
    output = str(event.get("output_text") or event.get("output_preview") or "")
    suffix = " · truncated" if status == "truncated" or event.get("truncated") else ""
    if tool_name == "read_file":
        target = str(args.get("path") or "").strip()
        return _tool_activity_summary(
            translator.t("runtime.tool.activity_read_file", path=target).strip(),
            f"read_file · {_count_label(_line_count(output), 'line', 'lines')}{suffix}",
        )
    if tool_name == "discover_project_guidance":
        target = str(args.get("path") or ".").strip()
        return _tool_activity_summary(
            translator.t("runtime.tool.activity_discover_project_guidance", path=target),
            f"discover_project_guidance · {_count_label(_guidance_file_count(output), 'file', 'files')}{suffix}",
        )
    if tool_name == "list_dir":
        target = str(args.get("path") or ".").strip()
        return _tool_activity_summary(
            translator.t("runtime.tool.activity_list_dir", path=target),
            f"list_dir · {_count_label(_tool_item_count(output), 'item', 'items')}{suffix}",
        )
    if tool_name == "search_files":
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return _tool_activity_summary(
            translator.t("runtime.tool.activity_search_files", root=root, pattern=pattern),
            f"search_files · {_count_label(_tool_item_count(output), 'match', 'matches')}{suffix}",
        )
    if tool_name == "fetch_url":
        target = str(args.get("url") or "").strip()
        return _tool_activity_summary(
            translator.t("runtime.tool.activity_fetch_url", url=target),
            f"fetch_url · {_count_label(_line_count(output), 'line', 'lines')}{suffix}",
        )
    return _tool_activity_summary(
        translator.t("runtime.tool.activity_update"), f"{tool_name} · done{suffix}"
    )


def _tool_activity_summary(heading: str, detail: str) -> str:
    return f"{heading}\n  {detail}"


def _line_count(text: str) -> int:
    if not text.strip():
        return 0
    return len(text.splitlines())


def _tool_item_count(preview: str) -> int:
    items = _json_preview_items(preview)
    if items:
        return len(items)
    return len([line for line in preview.splitlines() if line.strip()])


def _guidance_evidence_summary(preview: str, translator: Translator) -> tuple[str, ...]:
    try:
        payload = json.loads(preview)
    except json.JSONDecodeError:
        return _tool_evidence_summary(preview, translator)
    if not isinstance(payload, dict):
        return _tool_evidence_summary(preview, translator)
    files = payload.get("guidance_files")
    if not isinstance(files, list) or not files:
        return (translator.t("runtime.tool.no_output"),)
    return tuple(
        _trim_tool_evidence(str(item.get("path") or ""))
        for item in files[:_TOOL_EVIDENCE_ITEMS]
        if isinstance(item, dict)
    ) or (translator.t("runtime.tool.no_output"),)


def _guidance_file_count(preview: str) -> int:
    try:
        payload = json.loads(preview)
    except json.JSONDecodeError:
        return _tool_item_count(preview)
    if not isinstance(payload, dict):
        return _tool_item_count(preview)
    files = payload.get("guidance_files")
    return len(files) if isinstance(files, list) else 0


def _count_label(count: int, singular: str, plural: str) -> str:
    word = singular if count == 1 else plural
    return f"{count} {word}"


def _tool_evidence_summary(preview: str, translator: Translator) -> tuple[str, ...]:
    items = _json_preview_items(preview)
    if not items:
        items = [line.strip() for line in preview.splitlines() if line.strip()]
    if not items:
        return (translator.t("runtime.tool.no_output"),)
    return tuple(_trim_tool_evidence(item) for item in items[:_TOOL_EVIDENCE_ITEMS])


def _read_file_evidence_summary(output: str, translator: Translator) -> tuple[str, ...]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return (translator.t("runtime.tool.no_output"),)
    if len(lines) <= _READ_FILE_HEAD_EVIDENCE_ITEMS + _READ_FILE_TAIL_EVIDENCE_ITEMS:
        return tuple(_trim_tool_evidence(line) for line in lines)
    selected = [
        *lines[:_READ_FILE_HEAD_EVIDENCE_ITEMS],
        *lines[-_READ_FILE_TAIL_EVIDENCE_ITEMS:],
    ]
    return tuple(_trim_tool_evidence(line) for line in selected)


def _trim_tool_evidence(item: str) -> str:
    if len(item) <= _TOOL_EVIDENCE_CHARS:
        return item
    return item[: _TOOL_EVIDENCE_CHARS - 1].rstrip() + "…"


def _json_preview_items(preview: str) -> list[str]:
    try:
        value = json.loads(preview)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]
