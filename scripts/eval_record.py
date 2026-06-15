"""Opt-in recorder: capture real router output into committed fixtures.

Usage: python scripts/eval_record.py [--recorded-at 2026-06-15]
Not run in CI. Requires a working provider in config.yaml.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from linuxagent.config.loader import load_config
from linuxagent.eval.record import record_intent_router
from linuxagent.providers.factory import provider_factory

_REPO_ROOT = Path(__file__).resolve().parents[1]
_GOLDEN = _REPO_ROOT / "tests/eval/golden/intent_router.yaml"
_RECORDINGS = _REPO_ROOT / "tests/eval/recordings/intent_router"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recorded-at", default=None)
    args = parser.parse_args(argv)

    config = load_config()
    provider = provider_factory(config.api)
    count = asyncio.run(
        record_intent_router(
            provider,
            _GOLDEN,
            _RECORDINGS,
            provider_name=config.api.provider.value,
            model=config.api.model,
            recorded_at=args.recorded_at,
        )
    )
    print(f"recorded {count} intent-router cases to {_RECORDINGS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
