"""Export a stable index of Python YAML harness scenarios for TS parity planning."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def export_harness_fixtures(output: Path, scenario_dir: Path) -> None:
    from tests.harness.runner import _load_scenarios, _scenario_paths

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for path in _scenario_paths(scenario_dir):
            for scenario in _load_scenarios(path):
                record = {
                    "schemaVersion": 1,
                    "scenarioId": scenario.name,
                    "source": path.as_posix(),
                    "turnCount": len(scenario.turns),
                    "providerResponseCount": len(scenario.provider_responses),
                    "expectedKeys": sorted(scenario.expected.keys()),
                    "setupKeys": sorted(scenario.setup.keys()),
                }
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    output = Path(args[0]) if args else Path("ts/parity/fixtures/harness-scenarios.jsonl")
    scenario_dir = Path(args[1]) if len(args) > 1 else Path("tests/harness/scenarios")
    export_harness_fixtures(output, scenario_dir)


if __name__ == "__main__":
    main()
