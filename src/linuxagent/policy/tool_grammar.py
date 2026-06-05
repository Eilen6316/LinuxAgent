"""Small command grammar helpers for policy subcommand matching."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolGrammar:
    flags_with_values: frozenset[str] = frozenset()
    flags_without_values: frozenset[str] = frozenset()
    candidate_flags: frozenset[str] = frozenset()


_TOOL_GRAMMAR: dict[str, ToolGrammar] = {
    "kubectl": ToolGrammar(
        flags_with_values=frozenset({"-n", "--namespace", "--context", "--kubeconfig"}),
    ),
    "apt": ToolGrammar(
        flags_with_values=frozenset({"-o"}),
        flags_without_values=frozenset({"-y"}),
    ),
    "apt-get": ToolGrammar(
        flags_with_values=frozenset({"-o"}),
        flags_without_values=frozenset({"-y"}),
    ),
    "yum": ToolGrammar(
        flags_with_values=frozenset({"--setopt"}),
        flags_without_values=frozenset({"-y"}),
    ),
    "dnf": ToolGrammar(
        flags_with_values=frozenset({"--setopt"}),
        flags_without_values=frozenset({"-y"}),
    ),
    "docker": ToolGrammar(
        flags_with_values=frozenset({"-H", "--host", "--context"}),
    ),
    "systemctl": ToolGrammar(
        flags_with_values=frozenset({"-H", "--host"}),
        flags_without_values=frozenset({"--no-block", "--system", "--user", "--global"}),
    ),
    "pacman": ToolGrammar(
        candidate_flags=frozenset({"-R", "-Rs", "-Rns"}),
    ),
}


def candidate_subcommands(command: str | None, args: tuple[str, ...]) -> tuple[str, ...]:
    """Return non-option tokens that may be command verbs for policy matching."""
    if not args:
        return ()
    grammar = _TOOL_GRAMMAR.get(command or "")
    if grammar is None:
        return tuple(arg for arg in args if not arg.startswith("-"))
    candidates: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            candidates.extend(args[index + 1 :])
            break
        if arg in grammar.candidate_flags:
            candidates.append(arg)
            index += 1
            continue
        if _is_flag_with_inline_value(arg, grammar.flags_with_values):
            index += 1
            continue
        if arg in grammar.flags_with_values:
            index += 2 if index + 1 < len(args) else 1
            continue
        if _is_short_flag_bundle(arg, grammar):
            index += 1
            continue
        if arg.startswith("-") or arg in grammar.flags_without_values:
            index += 1
            continue
        candidates.append(arg)
        index += 1
    return tuple(candidates)


def _is_flag_with_inline_value(arg: str, flags: frozenset[str]) -> bool:
    return any(arg.startswith(f"{flag}=") for flag in flags)


def _is_short_flag_bundle(arg: str, grammar: ToolGrammar) -> bool:
    if len(arg) <= 2 or not arg.startswith("-") or arg.startswith("--"):
        return False
    return any(arg.startswith(flag) for flag in grammar.flags_with_values if flag.startswith("-"))
