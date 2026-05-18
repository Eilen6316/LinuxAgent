# Changelog

All notable changes to LinuxAgent are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- Audit hash-chain appends now hold a file lock across tail-hash lookup and
  write, so concurrent LinuxAgent processes do not race each other on
  `~/.linuxagent/audit.log`.
- Audit append now reads the tail of the JSONL log to find the previous hash
  instead of scanning the whole file on every write.
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
- Tool-call history with an unpaired assistant tool call is now repaired by
  inserting a structured redacted tool error before the next provider request,
  avoiding provider crashes without executing any tool.

### Changed

- Added runtime i18n configuration via top-level `language` (`zh-CN` or
  `en-US`) for LinuxAgent-owned fixed CLI/TUI text, slash help, confirmations,
  block messages, diagnostics, and display-only built-in metadata. Prompt
  templates, model-visible guidance, LLM final answers, audit JSON fields, MCP
  protocol fields, tool names, and policy ids remain stable machine/model
  surfaces.
- Build and security gates now verify locale catalog parity, packaged locale
  availability, and unregistered Chinese runtime string literals. English
  phrase scanning is available as a report-only inventory to avoid false
  positives on protocol strings and model-facing text.
- The lightweight learner / recommendation helpers moved internally from
  `linuxagent.intelligence` to `linuxagent.usage_insights`; the old import path
  remains as a compatibility re-export and the `intelligence` config key is
  unchanged.
- SSH execution now uses a manager-owned worker pool controlled by
  `cluster.max_workers` instead of creating a new one-worker pool for each
  remote command.
- Policy rules and conversation permissions now support structured argv-shape
  matching, including exact prefixes, token positions, and flag values, so an
  approval for one command shape cannot generalize to inserted or reordered
  arguments.
- Added an application-level `network` policy foundation for future LLM/web
  tools, with default-deny configuration, domain allow/deny matching,
  network-decision audit records, and `linuxagent check` visibility.
- Added an optional `fetch_url` tool behind the application network policy,
  with HTTP/HTTPS-only URL validation, DNS/IP SSRF guards, redirect rechecks,
  response budgets, and network/tool audit events.
- Added automatic parameter-collection wizard support for ambiguous
  multi-parameter operations, with `/resume` visibility, stable partial
  recovery checkpoints, and user documentation.
- LLM-visible tool calls now share one runtime budget: per-tool timeout,
  per-tool output limit, cumulative per-request output limit, and maximum
  tool-calling rounds. Runtime events include redacted args/output preview,
  sandbox metadata, status, output size, and truncation details.
- Source checkout bootstrap now seeds `~/.config/linuxagent/config.yaml` and
  installs a user-level `~/.local/bin/linuxagent` launcher, so users can start
  LinuxAgent from any directory without activating the checkout virtualenv.
- Optional embedding-backed intelligence tools are no longer exposed by provider
  default; set `intelligence.tools_enabled: true` to add recommendation,
  knowledge-base, and semantic-similarity tools to the LLM catalog.
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
- LinuxAgent self-capability questions are now routed through the operating
  manifest direct-answer path, so cache, memory, tool, safety, resume, and
  network-boundary answers come from the same maintainable self manual instead
  of cache-specific prompt rules.
- Slash-command help and completion now share one command catalog.
- `linuxagent audit summary` and `linuxagent audit inspect` now provide
  read-only audit diagnostics with decision counts, safety counts, hash-chain
  status, and redacted recent command details.
- MCP server exposure is now controlled by `mcp.tools`, keeping the stdio
  server read-only while allowing operators to disable individual tools.
- Added declarative local Skill manifests for planner guidance. Skills cannot
  include executable hooks.
- `linuxagent check` now reports MCP and Skill status and fails fast when Skill
  manifests are missing or invalid.
- MCP now exposes configurable read-only Skill summaries without returning full
  guidance bodies or execution handles.
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
  config and prompt data.

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
