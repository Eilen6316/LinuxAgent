"""Operating manifest loading for progressive product disclosure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .prompts_loader import load_prompt


@dataclass(frozen=True)
class ManifestSection:
    name: str
    title: str
    path: str


MANIFEST_SECTIONS: tuple[ManifestSection, ...] = (
    ManifestSection("identity", "Identity and project boundary", "manifest/identity.md"),
    ManifestSection("usage", "CLI usage and commands", "manifest/usage.md"),
    ManifestSection("planning", "Intent routing and planning", "manifest/planning.md"),
    ManifestSection(
        "session_resume", "Session resume and checkpoints", "manifest/session_resume.md"
    ),
    ManifestSection("memory", "History and learner memory", "manifest/memory.md"),
    ManifestSection("tools", "Tool catalog and sandbox metadata", "manifest/tools.md"),
    ManifestSection("execution", "Execution and output analysis", "manifest/execution.md"),
    ManifestSection("safety", "Policy, HITL, and audit", "manifest/safety.md"),
    ManifestSection("config", "Configuration and diagnostics", "manifest/config.md"),
    ManifestSection("network", "Network capability boundary", "manifest/network.md"),
    ManifestSection("limits", "Limits and non-promises", "manifest/limits.md"),
)


def manifest_index() -> str:
    lines = ["LinuxAgent operating manifest sections:"]
    lines.extend(f"- {section.name}: {section.title}" for section in MANIFEST_SECTIONS)
    return "\n".join(lines)


def operating_manifest_context(*, section_names: Iterable[str] | None = None) -> str:
    selected = _selected_sections(section_names)
    parts = [manifest_index()]
    parts.extend(load_prompt(section.path) for section in selected)
    return "\n\n".join(parts)


def _selected_sections(section_names: Iterable[str] | None) -> tuple[ManifestSection, ...]:
    if section_names is None:
        return MANIFEST_SECTIONS
    requested = set(section_names)
    return tuple(section for section in MANIFEST_SECTIONS if section.name in requested)
