"""libseccomp-backed BPF program generation for bubblewrap."""

from __future__ import annotations

import ctypes
import errno
import tempfile
from ctypes.util import find_library

from .profiles import DEFAULT_SECCOMP_DENY_SYSCALLS, SECCOMP_CRITICAL_DENY_SYSCALLS

SCMP_ACT_ALLOW = 0x7FFF0000
SCMP_ACT_ERRNO = 0x00050000


class SeccompUnavailableError(RuntimeError):
    """Raised when a seccomp BPF program cannot be generated."""


class SeccompProgram:
    def __init__(self, file: tempfile._TemporaryFileWrapper[bytes]) -> None:
        self._file = file

    @property
    def fd(self) -> int:
        return self._file.fileno()

    def close(self) -> None:
        self._file.close()


def build_default_seccomp_program() -> SeccompProgram:
    lib = _load_libseccomp()
    ctx = lib.seccomp_init(SCMP_ACT_ALLOW)
    if ctx is None:
        raise SeccompUnavailableError("libseccomp failed to initialize filter")
    try:
        unresolved: list[str] = []
        for syscall in sorted(DEFAULT_SECCOMP_DENY_SYSCALLS):
            syscall_number = lib.seccomp_syscall_resolve_name(syscall.encode("ascii"))
            if syscall_number < 0:
                # Modern syscalls may be unknown to an older libseccomp; record
                # the gap rather than silently dropping it. A critical syscall
                # that cannot be resolved fails closed below so the run never
                # claims seccomp it did not install.
                unresolved.append(syscall)
                continue
            rc = lib.seccomp_rule_add(ctx, _errno_action(errno.EPERM), syscall_number, 0)
            if rc < 0:
                raise SeccompUnavailableError(f"libseccomp failed adding rule: {syscall}")
        critical_unresolved = sorted(set(unresolved) & SECCOMP_CRITICAL_DENY_SYSCALLS)
        if critical_unresolved:
            raise SeccompUnavailableError(
                f"libseccomp cannot resolve critical syscalls: {', '.join(critical_unresolved)}"
            )
        program = tempfile.NamedTemporaryFile(  # noqa: SIM115 - caller owns returned fd
            prefix="linuxagent-seccomp-",
            suffix=".bpf",
        )
        rc = lib.seccomp_export_bpf(ctx, program.fileno())
        if rc < 0:
            program.close()
            raise SeccompUnavailableError("libseccomp failed exporting bpf")
        program.flush()
        program.seek(0)
        return SeccompProgram(program)
    finally:
        lib.seccomp_release(ctx)


def libseccomp_available() -> bool:
    try:
        _load_libseccomp()
    except SeccompUnavailableError:
        return False
    return True


def _load_libseccomp() -> ctypes.CDLL:
    library = find_library("seccomp")
    if not library:
        raise SeccompUnavailableError("libseccomp not found")
    try:
        lib = ctypes.CDLL(library)
    except OSError as exc:
        raise SeccompUnavailableError(f"libseccomp cannot be loaded: {exc}") from exc
    _configure_signatures(lib)
    return lib


def _configure_signatures(lib: ctypes.CDLL) -> None:
    lib.seccomp_init.argtypes = [ctypes.c_uint32]
    lib.seccomp_init.restype = ctypes.c_void_p
    lib.seccomp_release.argtypes = [ctypes.c_void_p]
    lib.seccomp_release.restype = None
    lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
    lib.seccomp_rule_add.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_int,
        ctypes.c_uint,
    ]
    lib.seccomp_rule_add.restype = ctypes.c_int
    lib.seccomp_export_bpf.argtypes = [ctypes.c_void_p, ctypes.c_int]
    lib.seccomp_export_bpf.restype = ctypes.c_int


def _errno_action(error_number: int) -> int:
    return SCMP_ACT_ERRNO | (error_number & 0xFFFF)


__all__ = [
    "SeccompProgram",
    "SeccompUnavailableError",
    "build_default_seccomp_program",
    "libseccomp_available",
]
