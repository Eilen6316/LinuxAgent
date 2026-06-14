"""Seccomp BPF generation tests."""

from __future__ import annotations

import os

import pytest

from linuxagent.sandbox.seccomp import build_default_seccomp_program, libseccomp_available


def test_default_seccomp_program_exports_bpf_when_libseccomp_is_available() -> None:
    if not libseccomp_available():
        pytest.skip("libseccomp is unavailable")

    program = build_default_seccomp_program()
    try:
        assert os.fstat(program.fd).st_size > 0
    finally:
        program.close()
