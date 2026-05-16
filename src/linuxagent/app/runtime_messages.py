"""Runtime event messages shown by the CLI UI."""

from __future__ import annotations

import json
from typing import Any

_TOOL_EVIDENCE_ITEMS = 3
_READ_FILE_HEAD_EVIDENCE_ITEMS = 2
_READ_FILE_TAIL_EVIDENCE_ITEMS = 3
_TOOL_EVIDENCE_CHARS = 180
_TOOL_ERROR_CHARS = 220


def tool_event_message(event: dict[str, Any]) -> str | None:
    phase = str(event.get("phase") or "")
    tool_name = str(event.get("tool_name") or "")
    raw_args = event.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    if phase == "start":
        return _tool_start_message(tool_name, args)
    if phase == "error":
        return _tool_error_message(tool_name, args, event)
    if phase == "end":
        return _tool_end_message(tool_name, args, event)
    return None


def tool_activity_message(event: dict[str, Any]) -> str | None:
    phase = str(event.get("phase") or "")
    tool_name = str(event.get("tool_name") or "")
    raw_args = event.get("args")
    args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
    if phase == "start":
        return _tool_start_message(tool_name, args)
    if phase == "error":
        return _tool_activity_error(tool_name, args, event)
    if phase == "end":
        return _tool_activity_end(tool_name, args, event)
    return None


def command_event_key(event: dict[str, Any]) -> tuple[str, str]:
    return (str(event.get("trace_id") or ""), str(event.get("command") or ""))


def runtime_event_message(event: dict[str, Any]) -> str | None:
    event_type = str(event.get("type") or "")
    phase = str(event.get("phase") or "")
    if event_type == "command":
        return _command_event_message(phase, event)
    if event_type == "command_batch":
        return _command_batch_event_message(phase, event)
    if event_type == "background_job":
        return _background_job_event_message(phase, event)
    if event_type == "activity":
        return _activity_event_message(phase)
    return None


def _command_event_message(phase: str, event: dict[str, Any]) -> str | None:
    command = str(event.get("command") or "")
    if phase == "start":
        return f"LinuxAgent 正在执行命令：{command}"
    if phase == "finish":
        return f"LinuxAgent 命令结束：exit {event.get('exit_code')}"
    return None


def _command_batch_event_message(phase: str, event: dict[str, Any]) -> str | None:
    count = int(event.get("count") or 0)
    if phase == "start":
        return f"LinuxAgent 正在并发执行 {count} 条只读命令"
    if phase == "finish":
        return f"LinuxAgent 并发只读命令已完成：{count} 条"
    return None


def _background_job_event_message(phase: str, event: dict[str, Any]) -> str | None:
    job_id = str(event.get("job_id") or "")
    status = str(event.get("status") or "")
    if phase == "start":
        return f"LinuxAgent 后台任务已启动：{job_id}"
    if phase == "finish":
        return f"LinuxAgent 后台任务结束：{job_id}（{status}）"
    return None


def _activity_event_message(phase: str) -> str | None:
    labels = {
        "classify": "LinuxAgent 正在分类意图",
        "plan": "LinuxAgent 正在规划命令",
        "policy": "LinuxAgent 正在评估安全策略",
        "waiting_confirm": "LinuxAgent 正在等待确认",
        "repair_plan": "LinuxAgent 正在生成修复方案",
        "analyze": "LinuxAgent 正在分析执行结果",
    }
    return labels.get(phase)


def _tool_start_message(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "read_file":
        return f"LinuxAgent 正在读取文件 {args.get('path') or ''}".strip()
    if tool_name == "list_dir":
        return f"LinuxAgent 正在列目录 {args.get('path') or '.'}"
    if tool_name == "search_files":
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return f"LinuxAgent 正在搜索 {root}: {pattern}"
    if tool_name == "repair_file_patch":
        files = args.get("files") if isinstance(args.get("files"), list) else []
        suffix = f" {', '.join(str(item) for item in files)}" if files else ""
        return f"LinuxAgent 正在重新读取文件并修复 diff{suffix}"
    return f"LinuxAgent 正在调用工具 {tool_name}"


def _tool_error_message(tool_name: str, args: dict[str, Any], event: dict[str, Any]) -> str:
    target = _tool_target(tool_name, args)
    reason = _human_tool_error(event.get("output_preview") or event.get("output_text"))
    location = f" {target}" if target else ""
    return f"LinuxAgent 工具未完成：{tool_name}{location} - {reason}"


def _tool_target(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name == "search_files":
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return f"{root}: {pattern}".strip()
    target = args.get("path")
    if isinstance(target, str) and target:
        return target
    return ""


def _human_tool_error(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return "unknown error"
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


def _tool_end_message(tool_name: str, args: dict[str, Any], event: dict[str, Any]) -> str | None:
    status = str(event.get("status") or "")
    if status not in {"allowed", "truncated"}:
        return None
    output = str(event.get("output_text") or event.get("output_preview") or "")
    suffix = "（输出已截断）" if status == "truncated" or event.get("truncated") else ""
    if tool_name == "read_file":
        evidence = _read_file_evidence_summary(output)
        heading = f"LinuxAgent 已读取文件 {args.get('path') or ''}{suffix}".strip()
        return _tool_evidence_message(heading, evidence)
    if tool_name == "list_dir":
        evidence = _tool_evidence_summary(output)
        return _tool_evidence_message(
            f"LinuxAgent 已列目录 {args.get('path') or '.'}{suffix}", evidence
        )
    if tool_name == "search_files":
        evidence = _tool_evidence_summary(output)
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return _tool_evidence_message(f"LinuxAgent 已搜索 {root}: {pattern}{suffix}", evidence)
    return None


def _tool_evidence_message(heading: str, evidence: tuple[str, ...]) -> str:
    bullets = "\n".join(f"  - {item}" for item in evidence)
    return f"{heading}\n  证据预览:\n{bullets}"


def _tool_activity_error(tool_name: str, args: dict[str, Any], event: dict[str, Any]) -> str:
    status = str(event.get("status") or "error")
    target = _tool_target(tool_name, args)
    label = f"{tool_name} {target}".strip()
    return _tool_activity_summary("LinuxAgent 正在记录工具状态", f"{label} · {status}")


def _tool_activity_end(tool_name: str, args: dict[str, Any], event: dict[str, Any]) -> str | None:
    status = str(event.get("status") or "")
    if status not in {"allowed", "truncated"}:
        return None
    output = str(event.get("output_text") or event.get("output_preview") or "")
    suffix = " · truncated" if status == "truncated" or event.get("truncated") else ""
    if tool_name == "read_file":
        target = str(args.get("path") or "").strip()
        return _tool_activity_summary(
            f"LinuxAgent 正在整理文件 {target}".strip(),
            f"read_file · {_count_label(_line_count(output), 'line', 'lines')}{suffix}",
        )
    if tool_name == "list_dir":
        target = str(args.get("path") or ".").strip()
        return _tool_activity_summary(
            f"LinuxAgent 正在整理目录 {target}",
            f"list_dir · {_count_label(_tool_item_count(output), 'item', 'items')}{suffix}",
        )
    if tool_name == "search_files":
        root = args.get("root") or "."
        pattern = args.get("pattern") or ""
        return _tool_activity_summary(
            f"LinuxAgent 正在整理搜索结果 {root}: {pattern}",
            f"search_files · {_count_label(_tool_item_count(output), 'match', 'matches')}{suffix}",
        )
    return _tool_activity_summary("LinuxAgent 正在更新工具结果", f"{tool_name} · done{suffix}")


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


def _count_label(count: int, singular: str, plural: str) -> str:
    word = singular if count == 1 else plural
    return f"{count} {word}"


def _tool_evidence_summary(preview: str) -> tuple[str, ...]:
    items = _json_preview_items(preview)
    if not items:
        items = [line.strip() for line in preview.splitlines() if line.strip()]
    if not items:
        return ("无输出",)
    return tuple(_trim_tool_evidence(item) for item in items[:_TOOL_EVIDENCE_ITEMS])


def _read_file_evidence_summary(output: str) -> tuple[str, ...]:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ("无输出",)
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
