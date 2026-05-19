"""Tool catalog inspection and validation."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from langchain_core.tools import BaseTool

from ..i18n import Translator, default_translator
from ..sandbox import SandboxRunnerKind, SandboxRuntimeLabel
from .sandbox import SANDBOX_METADATA_KEY, ToolHITLMode, tool_sandbox_record


class ToolCatalogError(ValueError):
    """Raised when LLM-visible tools fail catalog validation."""


@dataclass(frozen=True)
class ToolCatalogItem:
    tool: BaseTool
    name: str
    description: str
    sandbox: dict[str, object] | None
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class ToolCatalogReport:
    items: tuple[ToolCatalogItem, ...]

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.items)

    @property
    def errors(self) -> tuple[str, ...]:
        return tuple(f"{item.name}: {error}" for item in self.items for error in item.errors)

    @property
    def tools(self) -> tuple[BaseTool, ...]:
        return tuple(item.tool for item in self.items)


def inspect_tool_catalog(tools: Iterable[BaseTool]) -> ToolCatalogReport:
    tool_list = tuple(tools)
    counts = Counter(_tool_name(tool) for tool in tool_list)
    items = tuple(_catalog_item(tool, counts[_tool_name(tool)] > 1) for tool in tool_list)
    return ToolCatalogReport(items)


def require_valid_tool_catalog(tools: Iterable[BaseTool]) -> ToolCatalogReport:
    report = inspect_tool_catalog(tools)
    if not report.ok:
        raise ToolCatalogError("invalid LLM tool catalog: " + "; ".join(report.errors))
    return report


def format_tool_catalog_check(
    report: ToolCatalogReport,
    *,
    runner: SandboxRunnerKind,
    sandbox_enabled: bool,
    translator: Translator | None = None,
) -> str:
    tr = translator or default_translator()
    lines = [
        "tool_catalog:",
        f"  status: {_status(report.ok, tr)}",
        f"  runner: {runner.value}",
        f"  {tr.t('tool_catalog.field.sandbox_enabled')}: {_bool(sandbox_enabled, tr)}",
        f"  {tr.t('tool_catalog.field.runtime_label')}: "
        f"{_catalog_runtime_label(runner, sandbox_enabled).value}",
        f"  {tr.t('tool_catalog.field.isolation_note')}: "
        f"{_runtime_label_note(_catalog_runtime_label(runner, sandbox_enabled), tr)}",
    ]
    lines.extend(_format_tool_item(item, tr) for item in report.items)
    return "\n".join(lines)


def compact_tool_catalog_summary(report: ToolCatalogReport) -> str:
    if not report.items:
        return "No LLM-visible tools are enabled."
    parts = []
    for item in report.items:
        status = "ok" if item.ok else "error"
        parts.append(
            f"{item.name}({status}, profile={_profile(item)}, "
            f"network={_permission(item, 'network_access')}, hitl={_hitl(item)})"
        )
    return "; ".join(parts)


def _catalog_item(tool: BaseTool, duplicate: bool) -> ToolCatalogItem:
    record = tool_sandbox_record(tool)
    errors = list(_sandbox_errors(record))
    if duplicate:
        errors.append("duplicate tool name")
    return ToolCatalogItem(
        tool=tool,
        name=_tool_name(tool),
        description=str(getattr(tool, "description", "") or ""),
        sandbox=record,
        errors=tuple(errors),
    )


def _sandbox_errors(record: dict[str, object] | None) -> tuple[str, ...]:
    if record is None:
        return (f"missing {SANDBOX_METADATA_KEY} ToolSandboxSpec metadata",)
    errors: list[str] = []
    if not isinstance(record.get("profile"), str):
        errors.append("sandbox profile is missing")
    elif str(record["profile"]) not in _SANDBOX_PROFILE_VALUES:
        errors.append(f"invalid sandbox profile: {record['profile']}")
    permissions = record.get("permissions")
    if not isinstance(permissions, dict):
        errors.append("sandbox permissions are missing")
    else:
        errors.extend(_permission_errors(permissions))
    if "parallel_safe" in record and not isinstance(record.get("parallel_safe"), bool):
        errors.append("sandbox parallel_safe must be boolean")
    if "resource_keys" in record:
        resource_keys = record.get("resource_keys")
        if not isinstance(resource_keys, list) or not all(
            isinstance(item, str) and item for item in resource_keys
        ):
            errors.append("sandbox resource_keys must be a list of non-empty strings")
    return tuple(errors)


def _permission_errors(permissions: dict[object, object]) -> tuple[str, ...]:
    errors: list[str] = []
    hitl = permissions.get("hitl")
    if not isinstance(hitl, str):
        errors.append("sandbox HITL mode is missing")
    elif hitl not in _HITL_VALUES:
        errors.append(f"invalid sandbox HITL mode: {hitl}")
    for key in _BOOLEAN_PERMISSION_KEYS:
        if key in permissions and not isinstance(permissions[key], bool):
            errors.append(f"sandbox permission {key} must be boolean")
    return tuple(errors)


def _format_tool_item(item: ToolCatalogItem, translator: Translator) -> str:
    status = _status(item.ok, translator)
    return (
        f"  - name={item.name} status={status} profile={_profile(item)} "
        f"permissions={_permissions_summary(item, translator)} "
        f"network_access={_permission(item, 'network_access', translator)} "
        f"hitl={_hitl(item)} parallel_safe={_parallel_safe(item)} "
        f"resource_keys={_resource_keys(item)} allowed_roots={_allowed_roots(item)}"
        f"{_error_suffix(item)}"
    )


def _permissions_summary(item: ToolCatalogItem, translator: Translator) -> str:
    permissions = _permissions(item)
    active = [key for key in _SUMMARY_PERMISSION_KEYS if permissions.get(key) is True]
    return ",".join(active) if active else translator.t("common.none")


def _permissions(item: ToolCatalogItem) -> dict[str, object]:
    if item.sandbox is None:
        return {}
    permissions = item.sandbox.get("permissions")
    return permissions if isinstance(permissions, dict) else {}


def _profile(item: ToolCatalogItem) -> str:
    if item.sandbox is None:
        return "missing"
    value = item.sandbox.get("profile")
    return str(value) if isinstance(value, str) and value else "missing"


def _permission(item: ToolCatalogItem, key: str, translator: Translator | None = None) -> str:
    value = _permissions(item).get(key)
    if isinstance(value, bool):
        return _bool(value, translator) if translator is not None else str(value).lower()
    return translator.t("common.unknown") if translator is not None else "unknown"


def _hitl(item: ToolCatalogItem) -> str:
    value = _permissions(item).get("hitl")
    return value if isinstance(value, str) and value else "unknown"


def _allowed_roots(item: ToolCatalogItem) -> str:
    if item.sandbox is None:
        return "[]"
    roots = item.sandbox.get("allowed_roots")
    if not isinstance(roots, list):
        return "[]"
    return "[" + ",".join(str(root) for root in roots) + "]"


def _resource_keys(item: ToolCatalogItem) -> str:
    if item.sandbox is None:
        return "[]"
    keys = item.sandbox.get("resource_keys")
    if not isinstance(keys, list):
        return "[]"
    return "[" + ",".join(str(key) for key in keys if str(key)) + "]"


def _parallel_safe(item: ToolCatalogItem) -> str:
    value = item.sandbox.get("parallel_safe") if item.sandbox is not None else None
    if isinstance(value, bool):
        return str(value).lower()
    return "unknown"


def _error_suffix(item: ToolCatalogItem) -> str:
    return "" if item.ok else f" errors={'; '.join(item.errors)}"


def _tool_name(tool: BaseTool) -> str:
    return str(getattr(tool, "name", "") or "<unnamed>")


def _catalog_runtime_label(runner: SandboxRunnerKind, sandbox_enabled: bool) -> SandboxRuntimeLabel:
    if not sandbox_enabled or runner is SandboxRunnerKind.NOOP:
        return SandboxRuntimeLabel.NO_ISOLATION
    if runner is SandboxRunnerKind.LOCAL:
        return SandboxRuntimeLabel.PROCESS_LIMITS_ONLY
    return SandboxRuntimeLabel.FILESYSTEM_ISOLATION


def _runtime_label_note(label: SandboxRuntimeLabel, translator: Translator) -> str:
    key = f"tool_catalog.isolation.{label.value}"
    translated = translator.t(key)
    return translated if translated != key else label.value


def _status(ok: bool, translator: Translator) -> str:
    return translator.t("common.ok") if ok else translator.t("common.error")


def _bool(value: bool, translator: Translator) -> str:
    return translator.t("common.true") if value else translator.t("common.false")


_SANDBOX_PROFILE_VALUES = {
    "none",
    "read_only",
    "system_inspect",
    "workspace_write",
    "privileged_passthrough",
}
_HITL_VALUES = {mode.value for mode in ToolHITLMode}
_BOOLEAN_PERMISSION_KEYS = (
    "read_files",
    "write_files",
    "execute_commands",
    "system_inspect",
    "network_access",
)
_SUMMARY_PERMISSION_KEYS = _BOOLEAN_PERMISSION_KEYS
