# Changelog

All notable changes to LinuxAgent are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Terminal assistant responses now render Markdown formatting in the Rich
  response panel instead of showing raw Markdown markers such as `**bold**`
  and `###` headings.
- Interactive terminals now show transient working status for activity events,
  with a compact animated `Working` label that is cleared before confirmations,
  command output, and final responses.
- Simple conversational replies now use the intent router's final
  `DIRECT_ANSWER`/`CLARIFY` response directly, avoiding an extra serialized LLM
  completion before showing the answer.
- LLM-visible tools now fail closed when their catalog metadata is missing or
  invalid, returning structured denied tool events instead of binding unsafe
  tools into the provider loop.
- Workspace tool errors now render as short operator-facing messages with the
  tool name, target, and human-readable reason instead of raw internal JSON.
- Runtime activity output now suppresses adjacent duplicate progress lines
  while preserving full telemetry events.
- Command confirmations now preserve and display full policy details for
  inline interpreter and LOLBin commands, including all matched rules,
  capabilities, risk score, and the policy whitelist decision.
- Command confirmations now extract inline interpreter payloads into a
  numbered review block and mark truncated commands or payloads explicitly,
  so long `python3 -c` and shell `-c` requests are inspectable before approval.
- Inline interpreter commands such as `python3 -c` and `bash -c` are no
  longer routed through inherited-stdio interactive execution. Their streamed
  output is captured in `ExecutionResult.stdout`/`stderr` and is available to
  the command-result panel and analysis prompt.

### Changed

- Source checkout bootstrap now seeds `~/.config/linuxagent/config.yaml` and
  installs a user-level `~/.local/bin/linuxagent` launcher, so users can start
  LinuxAgent from any directory without activating the checkout virtualenv.
- Added a unified tool catalog used by runtime tool binding, `/tools` context,
  product context, and `linuxagent check`; check output now reports each
  tool's sandbox profile, permissions, network access, HITL mode, allowed
  roots, and runner isolation note.
- Added an operating manifest under `prompts/manifest/` for progressive
  LinuxAgent self-description. Direct-answer paths can receive the full
  product operating context, while normal operational planning still receives
  only the concise product context.
- Direct answers, the intent router, and planning prompts now receive concise
  LinuxAgent product context, including `/resume`, session history,
  checkpointing, learner memory boundaries, and the configured provider/model
  source, so self-capability questions stay accurate.
- Slash-command help and completion now share one command catalog.
- `linuxagent audit summary` and `linuxagent audit inspect` now provide
  read-only audit diagnostics with decision counts, safety counts, hash-chain
  status, and redacted recent command details.
- MCP server exposure is now controlled by `mcp.tools`, keeping the stdio
  server read-only while allowing operators to disable individual tools.
- Added declarative local Skill manifests for planner guidance and runbook
  extension. Skills cannot include executable hooks, and Skill runbooks reuse
  the existing policy validation path.
- `linuxagent check` now reports MCP and Skill status and fails fast when Skill
  manifests are missing, invalid, or contain read-only runbooks rejected by
  policy.
- MCP now exposes configurable read-only resources for runbook and Skill
  summaries without returning command strings, full guidance bodies, or
  execution handles.
- MCP runbook summaries now include explicit step counts and summary safety
  posture while keeping command strings redacted.
- Build verification now installs the built wheel and checks packaged MCP/Skill
  defaults plus importability of the new MCP and Skill modules.
- Workspace tool activity now includes concise evidence snippets from completed
  `read_file`, `list_dir`, and `search_files` calls. No-change file-plan
  answers also include the cited evidence so operators can see which file lines
  or search results the model used.
- File-patch repair is stricter about regenerating diffs from current file
  snapshots, accepts JSON embedded in model prose or fenced blocks, and keeps
  terminal failure messages shorter by truncating large target snapshots.
- Conversation-history questions now stay on the direct-answer path instead of
  falling into command or file planning, so chat-only requests do not expose
  internal no-change evidence errors.
- Added optional provider-side prompt cache keys and `llm.usage` telemetry for
  cached input tokens, following Codex's cache-hit observability shape without
  caching final assistant answers locally.
- Provider-side prompt cache keys now default on; unsupported backends are
  retried once without the cache key and downgraded in-memory.
- Workspace evidence previews for `read_file` now come from the same bounded
  output sent to the agent and include both the start and end of longer read
  windows, making file-edit evidence less misleading.
- Planner and repair prompts now steer static file or script creation toward
  `FilePatchPlan` and keep inline interpreter commands short and reviewable
  when runtime output genuinely requires them.

## [4.1.0] - 2026-05-07

### Added

- General system health runbook for server-status requests, covering uptime,
  memory, filesystem usage, and failed systemd units.
- Package inventory and OS-version runbooks for common local diagnostic
  requests.
- Direct-answer prompt path for conversational capability questions, avoiding
  `echo` command plans and HITL prompts for non-execution answers.
- Terminal-friendly analysis prompt for plain-text summaries without Markdown
  formatting.
- Red-team adversarial policy harness with 24 command-agent attack cases.
- Shell-structure policy analysis for pipelines, subshells, command
  substitution, redirects, and nested shell execution.
- Deterministic LOLBin and interpreter-escape detection for patterns such as
  network-to-shell pipelines, `find -exec`, `xargs`, `awk system()`, editor
  shell escapes, and interpreter inline execution.
- Hypothesis fuzzing for shell-structure parsing.
- Policy latency benchmark report with P50/P95/P99 timings.
- Optional HTTP audit sink that preserves local append-first audit behavior and
  records sink delivery failures locally.
- Telemetry exporter modes for local JSONL, console, OTLP HTTP JSON, and none.
- Landlock sandbox design document covering capability probes, fallback order,
  compatibility limits, and implementation slices.
- Read-only stdio MCP server prototype exposing policy classification and audit
  verification without command execution.

### Fixed

- Tool-backed planning now retries once without tools when the model returns
  prose instead of a strict JSON `CommandPlan`.
- Localhost-style `CommandPlan.target_hosts` values now stay local instead of
  being treated as unresolved SSH cluster targets.
- DeepSeek defaults no longer enable embedding-backed intelligence tools unless
  explicitly configured.
- Multi-command LLM plans now continue through all successful planned steps
  instead of stopping after the first command.

### Changed

- README now presents the completed security-depth work as a project narrative
  instead of scattering it only across implementation plans.
- Release workflow selects release notes from the pushed tag name instead of
  hard-coding the v4.0.0 release body.

## [4.0.0] - 2026-04-26

LinuxAgent v4.0.0 is the first formal release of the rewritten operations
assistant. It replaces the earlier prototype with a LangGraph-based,
policy-driven, audited CLI for controlled human-in-the-loop Linux operations.

### Added

- LangGraph state machine with explicit parse, policy, confirm, execute, and
  analyze stages.
- Capability-based policy engine with `SAFE`, `CONFIRM`, `BLOCK`, risk scores,
  capabilities, matched rules, and runtime YAML policy overrides.
- Structured JSON `CommandPlan` validation before policy evaluation.
- Eleven YAML runbooks for common operations diagnostics, with multi-step
  orchestration and per-step policy checks.
- SSH cluster execution with batch confirmation, host-key verification, and
  remote shell-syntax guards.
- Hash-chained JSONL audit log at `~/.linuxagent/audit.log`, plus
  `linuxagent audit verify`.
- Output redaction and guarded tool results before LLM-facing analysis paths.
- Local telemetry JSONL spans with trace IDs.
- Resource threshold alerts for CPU, memory, and root filesystem usage.
- Unit, integration, security, type, lint, harness, optional-provider, and
  wheel-install verification gates.
- Public project governance files: `SECURITY.md`, `CONTRIBUTING.md`,
  `CODE_OF_CONDUCT.md`, issue templates, and PR template.
- v3 to v4 migration guide, threat model, production-readiness checklist, and
  formal release notes.
- Reproducible install constraints in `constraints.txt`.

### Changed

- Package metadata now marks v4.0.0 as a stable release instead of a development
  alpha.
- Configuration uses Pydantic v2 fail-fast validation and requires user config
  files to be owned by the current user and `chmod 600`.
- Secrets are configured through `config.yaml`; `.env` is not used for secret
  values.
- The README family, PyPI metadata, CHANGELOG, and release notes use the same
  v4.0.0 release narrative.
- CI publishes coverage artifacts and runs build verification against packaged
  config, prompt, and runbook data.

### Removed

- The frozen v3 code path is no longer part of the active package.
- `setup.py` and ad hoc dependency files are replaced by `pyproject.toml` plus
  release constraints.

### Security

- `shell=True`, `AutoAddPolicy`, bare `except:`, and graph-node `input()` are
  blocked by CI red-line checks.
- LLM-generated commands require confirmation on first use.
- Destructive commands never enter the session whitelist.
- Non-TTY confirmation requests auto-deny.
- SSH cluster mode blocks shell chaining, redirects, substitutions, and variable
  expansion before execution.
- Tool outputs are redacted and guarded before entering the LLM tool loop.

### Migration

This release is not a drop-in upgrade from v3. See
[docs/migration-v3-to-v4.md](docs/migration-v3-to-v4.md).

[Unreleased]: https://github.com/Eilen6316/LinuxAgent/compare/v4.1.0...HEAD
[4.1.0]: https://github.com/Eilen6316/LinuxAgent/compare/v4.0.0...v4.1.0
[4.0.0]: https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.0.0
