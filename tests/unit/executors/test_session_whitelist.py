"""Session whitelist tests (R-HITL-01 / R-HITL-03)."""

from __future__ import annotations

from linuxagent.executors.session_whitelist import SessionWhitelist


def test_add_and_contains_exact_match() -> None:
    wl = SessionWhitelist()
    assert wl.add("ls -la") is True
    assert wl.contains("ls -la") is True


def test_whitespace_normalisation() -> None:
    wl = SessionWhitelist()
    wl.add("ls   -la")
    assert wl.contains("ls -la") is True
    assert wl.contains("ls\t-la") is True


def test_flag_reorder_not_normalised() -> None:
    """Different argument order is a different command, on purpose."""
    wl = SessionWhitelist()
    wl.add("ls -l -a")
    assert wl.contains("ls -a -l") is False


def test_destructive_rejected() -> None:
    wl = SessionWhitelist()
    assert wl.add("rm -rf /tmp/x") is False
    assert wl.contains("rm -rf /tmp/x") is False


def test_destructive_rejected_when_already_approved_concept() -> None:
    """Even after an embed trick, destructive commands never enter."""
    wl = SessionWhitelist()
    assert wl.add("systemctl stop nginx") is False
    assert len(wl) == 0


def test_record_hit_increments_counter() -> None:
    wl = SessionWhitelist()
    wl.add("ls")
    wl.record_hit("ls")
    wl.record_hit("ls")
    [entry] = wl.snapshot()
    assert entry.hit_count == 2


def test_record_hit_unknown_command_is_noop() -> None:
    wl = SessionWhitelist()
    wl.record_hit("never-added")  # must not raise
    assert len(wl) == 0


def test_add_unparseable_command_rejected() -> None:
    wl = SessionWhitelist()
    assert wl.add("echo 'unterminated") is False


def test_contains_unparseable_returns_false() -> None:
    wl = SessionWhitelist()
    wl.add("ls")
    assert wl.contains("echo 'unterminated") is False


def test_add_is_idempotent_for_repeated_approval() -> None:
    wl = SessionWhitelist()
    wl.add("ls")
    wl.add("ls")
    assert len(wl) == 1
