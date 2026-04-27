"""O(1) command usage learner with secure JSON persistence."""

from __future__ import annotations

import json
import os
import shlex
from dataclasses import asdict, dataclass
from pathlib import Path

from ..interfaces import ExecutionResult
from ..security import redact_text


@dataclass
class CommandStats:
    count: int = 0
    success_count: int = 0
    total_duration: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.count if self.count else 0.0

    @property
    def avg_duration(self) -> float:
        return self.total_duration / self.count if self.count else 0.0


class CommandLearner:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._stats: dict[str, CommandStats] = {}

    def record(self, command: str, result: ExecutionResult) -> None:
        key = self.normalize(command)
        stats = self._stats.setdefault(key, CommandStats())
        stats.count += 1
        if result.exit_code == 0:
            stats.success_count += 1
        stats.total_duration += result.duration

    def stats_for(self, command: str) -> CommandStats | None:
        return self._stats.get(self.normalize(command))

    def top_commands(self, limit: int = 5) -> list[tuple[str, CommandStats]]:
        ranked = sorted(
            self._stats.items(),
            key=lambda item: (item[1].count, item[1].success_rate),
            reverse=True,
        )
        return ranked[:limit]

    def save(self, path: Path | None = None) -> None:
        target = path or self._path
        if target is None:
            raise ValueError("path is required to save learner state")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(fd)
        payload = {key: asdict(stats) for key, stats in self._stats.items()}
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(target, 0o600)

    def load(self, path: Path | None = None) -> None:
        target = path or self._path
        if target is None or not target.is_file():
            return
        raw = json.loads(target.read_text(encoding="utf-8"))
        self._stats = {key: CommandStats(**value) for key, value in raw.items()}

    @staticmethod
    def normalize(command: str) -> str:
        stripped = command.strip()
        if not stripped:
            return ""
        try:
            normalized = shlex.join(_redact_sensitive_tokens(shlex.split(stripped)))
        except ValueError:
            normalized = stripped
        return redact_text(normalized).text


def _redact_sensitive_tokens(tokens: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for token in tokens:
        if redact_next:
            redacted.append("***redacted***")
            redact_next = False
            continue
        lowered = token.lower()
        if lowered in {"-p", "--password", "--password1", "--password2", "--password3"}:
            redacted.append(token)
            redact_next = True
        elif lowered.startswith(
            ("-p", "--password=", "--password1=", "--password2=", "--password3=")
        ):
            prefix = token.split("=", 1)[0] if "=" in token else token[:2]
            separator = "=" if "=" in token else ""
            redacted.append(f"{prefix}{separator}***redacted***")
        else:
            redacted.append(token)
    return redacted
