"""cgroup v2 helper tests."""

from __future__ import annotations

from linuxagent.sandbox.cgroup import limits_from_resource_limits


def test_resource_limits_map_to_cgroup_v2_files() -> None:
    limits = limits_from_resource_limits({"memory_mb": 32, "process_count": 4, "cpu_seconds": 1.5})

    assert limits.memory_max == 33_554_432
    assert limits.pids_max == 4
    assert limits.cpu_max == (150_000, 100_000)
