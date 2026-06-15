"""Deterministic shell structure extraction for policy evaluation."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

_CONTROL_OPERATORS: frozenset[str] = frozenset({"|", "||", "&", "&&", ";"})
_WRITE_REDIRECT_OPERATORS: frozenset[str] = frozenset({">", ">>", ">|", "<>", "&>", "&>>"})
_READ_REDIRECT_OPERATORS: frozenset[str] = frozenset({"<", "<<", "<<<"})
_SHELL_INTERPRETERS: frozenset[str] = frozenset({"sh", "bash", "zsh"})
# Command runners that execute an arbitrary inner command supplied as a ``-c``
# string (``su``/``runuser``/``flock``) or as the trailing operand (``watch``).
# Their inner command must be re-evaluated at its true severity rather than
# treated as inert wrapper arguments.
_COMMAND_STRING_RUNNERS: frozenset[str] = frozenset({"su", "runuser", "flock"})
_WATCH_VALUE_FLAGS: frozenset[str] = frozenset({"-n", "--interval"})


@dataclass(frozen=True)
class ShellRedirect:
    operator: str
    target: str | None

    @property
    def is_write(self) -> bool:
        return self.operator in _WRITE_REDIRECT_OPERATORS


@dataclass(frozen=True)
class ShellStructure:
    tokens: tuple[str, ...]
    pipeline_segments: tuple[str, ...] = ()
    control_operators: tuple[str, ...] = ()
    redirects: tuple[ShellRedirect, ...] = ()
    command_substitutions: tuple[str, ...] = ()
    subshells: tuple[str, ...] = ()
    nested_commands: tuple[str, ...] = ()
    sequenced_commands: tuple[str, ...] = ()
    parse_error: str | None = None

    @property
    def child_commands(self) -> tuple[str, ...]:
        commands = (
            *self.pipeline_segments,
            *self.sequenced_commands,
            *self.nested_commands,
            *self.command_substitutions,
            *self.subshells,
        )
        return tuple(dict.fromkeys(command for command in commands if command.strip()))


@dataclass(frozen=True)
class _TopLevelScan:
    pipeline_segments: tuple[str, ...]
    control_operators: tuple[str, ...]
    command_substitutions: tuple[str, ...]
    subshells: tuple[str, ...]
    parse_error: str | None = None
    sequenced_commands: tuple[str, ...] = ()


def analyze_shell_structure(command: str) -> ShellStructure:
    try:
        tokens = shell_tokens(command)
    except ValueError as exc:
        return ShellStructure(tokens=(), parse_error=f"shell structure parse failed: {exc}")
    scan = _scan_top_level(command)
    parse_error = scan.parse_error or _redirect_parse_error(tokens)
    return ShellStructure(
        tokens=tokens,
        pipeline_segments=scan.pipeline_segments,
        control_operators=scan.control_operators,
        redirects=_redirects(tokens),
        command_substitutions=scan.command_substitutions,
        subshells=scan.subshells,
        nested_commands=(
            *_interpreter_command_strings(tokens),
            *_runner_command_strings(tokens),
        ),
        sequenced_commands=scan.sequenced_commands,
        parse_error=parse_error,
    )


def shell_tokens(command: str) -> tuple[str, ...]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    return tuple(lexer)


@dataclass
class _Segmenter:
    """Accumulate top-level segments while scanning a command string.

    ``segments`` are pipe-delimited (for the network-to-shell lolbin heuristic);
    ``sequenced`` are split at every sequencing/pipe operator and newline so each
    top-level simple command is re-evaluated independently (head-based BLOCK
    rules must see the 2nd..nth command of ``a && b``/``a; b``/``a\\nb``).
    """

    segments: list[str] = field(default_factory=list)
    controls: list[str] = field(default_factory=list)
    substitutions: list[str] = field(default_factory=list)
    subshells: list[str] = field(default_factory=list)
    sequenced: list[str] = field(default_factory=list)
    start: int = 0
    seq_start: int = 0

    def on_subshell(self, command: str, body: str, index: int, end: int) -> None:
        self.subshells.append(body.strip())
        self.controls.append("(")
        self.sequenced.append(command[self.seq_start : index].strip())
        self.seq_start = end

    def on_newline(self, command: str, index: int) -> None:
        self.sequenced.append(command[self.seq_start : index].strip())
        self.seq_start = index + 1

    def on_operator(self, command: str, operator: str, index: int) -> None:
        self.controls.append(operator)
        if operator == "|":
            self.segments.append(command[self.start : index].strip())
        self.sequenced.append(command[self.seq_start : index].strip())
        self.start = index + len(operator)
        self.seq_start = self.start

    def finalize(self, command: str) -> _TopLevelScan:
        if "|" in self.controls:
            self.segments.append(command[self.start :].strip())
        self.sequenced.append(command[self.seq_start :].strip())
        seq_filtered = tuple(item for item in self.sequenced if item)
        return _TopLevelScan(
            tuple(item for item in self.segments if item),
            tuple(self.controls),
            tuple(item for item in self.substitutions if item),
            tuple(item for item in self.subshells if item),
            # Only surface sequenced children when a real split happened; a single
            # segment is the whole command and must not be re-evaluated as its own
            # child (that would recurse to the depth cap on every command).
            sequenced_commands=seq_filtered if len(seq_filtered) > 1 else (),
        )


def _scan_top_level(command: str) -> _TopLevelScan:
    seg = _Segmenter()
    index = 0
    state = _ScannerState()
    while index < len(command):
        substitution = _command_substitution_at(command, index, state)
        if substitution is not None:
            body, end, parse_error = substitution
            if parse_error is not None:
                return _TopLevelScan((), (), (), (), parse_error)
            seg.substitutions.append(body.strip())
            index = end
            continue
        advance = _quoted_advance(command, index, state)
        if advance is not None:
            index = advance
            continue
        if command[index] == "(":
            body, end, parse_error = _subshell_at(command, index)
            if parse_error is not None:
                return _TopLevelScan((), (), (), (), "unclosed subshell")
            seg.on_subshell(command, body, index, end)
            index = end
            continue
        if command[index] in "\n\r":
            seg.on_newline(command, index)
            index = seg.seq_start
            continue
        operator = _control_operator_at(command, index)
        if operator is not None:
            seg.on_operator(command, operator, index)
            index = seg.start
            continue
        index += 1
    return seg.finalize(command)


def _subshell_at(command: str, index: int) -> tuple[str, int, str | None]:
    body, end = _read_balanced_parentheses(command, index)
    if body is None:
        return "", end, "unclosed subshell"
    return body, end, None


def _command_substitution_at(
    command: str,
    index: int,
    state: _ScannerState,
) -> tuple[str, int, str | None] | None:
    if state.escaped or state.quote == "'":
        return None
    if command[index] == "`":
        end = _find_backtick_end(command, index + 1)
        if end is None:
            return "", len(command), "unclosed command substitution"
        return command[index + 1 : end], end + 1, None
    if command.startswith("$(", index):
        body, end = _read_balanced_parentheses(command, index + 1)
        if body is None:
            return "", end, "unclosed command substitution"
        return body, end, None
    return None


@dataclass
class _ScannerState:
    quote: str | None = None
    escaped: bool = False


def _quoted_advance(command: str, index: int, state: _ScannerState) -> int | None:
    char = command[index]
    if state.escaped:
        state.escaped = False
        return index + 1
    if char == "\\" and state.quote != "'":
        state.escaped = True
        return index + 1
    if state.quote is not None:
        if char == state.quote:
            state.quote = None
        return index + 1
    if char in {"'", '"'}:
        state.quote = char
        return index + 1
    if char == "`":
        return _skip_backtick(command, index)
    return None


def _skip_backtick(command: str, index: int) -> int:
    end = _find_backtick_end(command, index + 1)
    return len(command) if end is None else end + 1


def _find_backtick_end(command: str, start: int) -> int | None:
    escaped = False
    for index in range(start, len(command)):
        char = command[index]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "`":
            return index
    return None


def _read_balanced_parentheses(command: str, open_index: int) -> tuple[str | None, int]:
    state = _ScannerState()
    depth = 0
    index = open_index
    while index < len(command):
        advance = _quoted_advance(command, index, state)
        if advance is not None:
            index = advance
            continue
        char = command[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return command[open_index + 1 : index], index + 1
        index += 1
    return None, len(command)


def _control_operator_at(command: str, index: int) -> str | None:
    for operator in ("&&", "||", "|", ";", "&"):
        if command.startswith(operator, index):
            if operator == "&" and command.startswith("&>", index):
                return None
            return operator
    return None


def _redirects(tokens: tuple[str, ...]) -> tuple[ShellRedirect, ...]:
    redirects: list[ShellRedirect] = []
    index = 0
    while index < len(tokens):
        operator, target_index = _redirect_at(tokens, index)
        if operator is None:
            index += 1
            continue
        target = tokens[target_index] if target_index < len(tokens) else None
        redirects.append(ShellRedirect(operator=operator, target=target))
        index = target_index + 1
    return tuple(redirects)


def _redirect_parse_error(tokens: tuple[str, ...]) -> str | None:
    for redirect in _redirects(tokens):
        if redirect.target is None:
            return f"redirect {redirect.operator!r} is missing a target"
    return None


def _redirect_at(tokens: tuple[str, ...], index: int) -> tuple[str | None, int]:
    token = tokens[index]
    if token in _WRITE_REDIRECT_OPERATORS or token in _READ_REDIRECT_OPERATORS:
        return token, index + 1
    if token.isdigit() and index + 1 < len(tokens):
        operator = tokens[index + 1]
        if operator in _WRITE_REDIRECT_OPERATORS or operator in _READ_REDIRECT_OPERATORS:
            return operator, index + 2
    return None, index


def _interpreter_command_strings(tokens: tuple[str, ...]) -> tuple[str, ...]:
    if not tokens or tokens[0] not in _SHELL_INTERPRETERS:
        return ()
    commands: list[str] = []
    for index, arg in enumerate(tokens[1:], start=1):
        if index + 1 < len(tokens) and (arg == "-c" or (arg.startswith("-") and "c" in arg[1:])):
            commands.append(tokens[index + 1])
    return tuple(command for command in commands if command)


def _runner_command_strings(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Extract the inner shell command from command-runner wrappers.

    ``su``/``runuser``/``flock`` run a command supplied via ``-c``/``--command``;
    ``watch`` runs its trailing operand through a shell. Surfacing that payload as
    a child command lets the engine re-evaluate it at its real severity (e.g.
    ``watch 'rm -rf /etc'`` is judged as ``rm -rf /etc``) instead of treating the
    destructive command as inert wrapper arguments.
    """
    if not tokens:
        return ()
    if tokens[0] == "watch":
        command = _watch_inner_command(tokens)
        return (command,) if command else ()
    if tokens[0] in _COMMAND_STRING_RUNNERS:
        return _dash_c_command_strings(tokens)
    return ()


def _dash_c_command_strings(tokens: tuple[str, ...]) -> tuple[str, ...]:
    commands: list[str] = []
    for index, arg in enumerate(tokens[1:], start=1):
        if arg in {"-c", "--command"} and index + 1 < len(tokens):
            commands.append(tokens[index + 1])
        elif arg.startswith("--command="):
            commands.append(arg[len("--command=") :])
    return tuple(command for command in commands if command.strip())


def _watch_inner_command(tokens: tuple[str, ...]) -> str | None:
    index = 1
    while index < len(tokens):
        arg = tokens[index]
        if arg == "--":
            index += 1
            break
        if arg in _WATCH_VALUE_FLAGS and index + 1 < len(tokens):
            index += 2
            continue
        if arg.startswith("--interval=") or (arg.startswith("-n") and len(arg) > 2):
            index += 1
            continue
        if arg.startswith("-"):
            index += 1
            continue
        break
    operand = tokens[index:]
    return " ".join(operand) if operand else None
