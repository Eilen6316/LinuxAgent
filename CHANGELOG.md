# Changelog

All notable changes to LinuxAgent are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Plan 6 foundation

- `src/linuxagent/ui/console.py`: `prompt_toolkit`-driven async prompt session with theme-aware Rich rendering
- `tests/harness/`: YAML scenario harness runner plus HITL and cluster scenarios
- `.github/workflows/release.yml`: tag-driven build + GitHub Release flow
- `Makefile build`: wheel + sdist build target
- `tests/integration/`: optional integration coverage for executor, graph, and SSH policy wiring
- `scripts/verify_wheel_install.sh`: post-build wheel install verification
- `docs/quickstart.md`, `docs/development.md`, `docs/release.md`

### Changed — release readiness

- `README.md` rewritten for the v4 codebase and current release workflow
- CI build job now verifies wheel installation after artifact build
- frozen `v3` source removed from the repository; `v4` is now the only active code path

### Added — Plan 1 skeleton

- `src/linuxagent/` v4 package under PyPA src-layout
- `src/linuxagent/config/models.py`: Pydantic v2 configuration models (fail-fast validation, `SecretStr` for secrets, `frozen=True`)
- `src/linuxagent/config/loader.py`: multi-source loader with `0o600` + owner checks for all user-supplied paths (R-SEC-04, R-HITL prerequisites)
- `src/linuxagent/interfaces/`: `LLMProvider`, `CommandExecutor`, `UserInterface`, `BaseService` ABCs; `ExecutionResult` / `SafetyResult` / `SafetyLevel` sentinels
- `src/linuxagent/container.py`: minimal DI container (grows across Plan 2–6)
- `src/linuxagent/logger.py`: JSON (production) + Rich console (dev) handlers
- `src/linuxagent/cli.py`: argparse entry point, `linuxagent check` subcommand validates config
- `pyproject.toml`: PEP 517/621 build; LangChain Core / LangGraph / Pydantic pinned
- `Makefile`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml` enforcing R-SEC / R-QUAL / R-HITL red-lines
- `configs/default.yaml`, `configs/example.yaml` template
- `scripts/bootstrap.sh` one-shot dev environment setup (chmod 600 on generated `./config.yaml`)
- `tests/unit/test_framework_ready.py`, `tests/unit/test_config.py`

### Changed — breaking (v3 → v4)

- Package name is `linuxagent` (was top-level `src.*`)
- `setup.py` + `requirements.txt` removed in favor of `pyproject.toml` (single source of truth)
- `src/` moved to `legacy/src_v3/`; all v3 imports break
- `.env` no longer supported — configuration lives in `config.yaml` only (see `.work/change/2026-04-23-config-yaml-only.md`)

### Security

- `shell=True`, `AutoAddPolicy`, bare `except:` banned at CI level (see `.work/rule/baseline.md` R-SEC-01 / R-SEC-03 / R-QUAL-01)
- HITL ground rules landed (`.work/rule/baseline.md` R-HITL-01..06); concrete enforcement in Plan 2 and Plan 4
