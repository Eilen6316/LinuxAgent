"""pytest entrypoint for the YAML harness."""

from __future__ import annotations

import os
from pathlib import Path

from .runner import HarnessRunner, _load_scenarios, _scenario_paths


async def test_harness_scenarios() -> None:
    scenario_dir = Path(
        os.environ.get("LINUXAGENT_HARNESS_SCENARIOS", "tests/harness/scenarios")
    )
    runner = HarnessRunner()
    for path in _scenario_paths(scenario_dir):
        for scenario in _load_scenarios(path):
            await runner.run_scenario(scenario)
