# LinuxAgent vNext

LinuxAgent vNext keeps Python v4 as the default release runtime while the
TypeScript v5 rewrite remains experimental.

The TypeScript runtime is experimental. Python v4 remains the default release runtime until parity gates pass.

## TypeScript v5 Migration Status

- Added an explicit `make cutover-check` target for default-runtime switch
  readiness.
- Added a manual `cutover-readiness` CI job that runs only through
  `workflow_dispatch` with `run_cutover_check=true`.
- Kept ordinary push, pull request, and release workflows on the Python v4
  release path.
- Expanded `make ts-parity` so audit verifier tamper detection is a real TS
  parity check instead of a placeholder summary.
- Added TS sandbox parity coverage for fail-closed safe profiles and explicit
  `noop` passthrough metadata.
- Added TS output-redaction parity coverage for model-facing bearer/API token
  redaction and bounded truncation.
- Added TS file patch parity coverage for transactional apply, rollback on
  partial failure, and runtime path-policy fail-closed behavior.
- Added TS HITL session-permission parity coverage for same-thread and
  resume-scoped approvals.
- Added TS SSH parity coverage for strict known-host OpenSSH argv and remote
  shell metacharacter confirmation.
- Added TS harness fixture parity coverage for the required scenario index.
- Added TS red-team policy parity coverage for protected tree deletion,
  protected block-device mutation, network-to-shell, service mutation, and mkfs
  cases.
- Recorded fresh `make cutover-check` evidence for the TS migration gate while
  keeping Python v4 as the default runtime until a separate cutover change.
- Kept `make ts-check` and `make ts-parity` as experimental TS signals until
  parity gates are promoted.

## Cutover Rule

No default runtime switch happens without a separate cutover change. Before TS
can become the default `linuxagent` runtime, maintainers must have fresh passing
evidence for:

- `make lint`
- `make type`
- `make security`
- `make test`
- `make sandbox`
- `make red-team`
- `make harness`
- `make verify-build`
- `make ts-check`
- `make ts-parity`

## Rollback Path

If a promoted TS default runtime ships with a P0 safety regression:

1. restore the Python `linuxagent` entry point as default
2. keep TS available only as `linuxagent-ts` if that path remains safe
3. publish a security advisory if execution, HITL, audit, or sandbox boundaries
   were affected
4. add a regression fixture before re-enabling TS as default
