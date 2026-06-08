# TS SSH Library Decision

- **Date:** 2026-06-08
- **Decision:** accept OpenSSH subprocess wrapper for the first TS remote-execution slice
- **Reason:** OpenSSH can enforce unknown-host rejection through explicit
  `StrictHostKeyChecking=yes` and `UserKnownHostsFile=<known_hosts>` arguments.
  The TS wrapper can build an argv-only `ssh` invocation and test those exact
  arguments through a fake process transport without contacting a real host.
- **Rejected:** `node-ssh` because it wraps `ssh2` and does not make
  LinuxAgent's known-host rejection boundary clearer than using `ssh2`
  directly.
- **Rejected for first slice:** `ssh2` because it requires a local host-verifier
  adapter and known-host parser before LinuxAgent can prove RejectPolicy-like
  behavior. It can be reconsidered later if that adapter is implemented and
  tested.

| Candidate | Known-host reject default | Host verifier hook | Key-file handling | Cancellation/timeout | Testable transport | Decision |
|---|---:|---:|---:|---:|---:|---|
| `ssh2` | no | yes | yes | yes | yes | reject for first slice |
| `node-ssh` | no | indirect | yes | limited | limited | reject |
| OpenSSH subprocess | yes, with explicit options | n/a | yes | yes | yes | accept |

## Boundary

The TS implementation must build `ssh` as an argv list. It must not use
`shell: true` or shell-string process execution. Unknown hosts must be rejected
by passing `-o StrictHostKeyChecking=yes` and an explicit
`-o UserKnownHostsFile=...`.

If OpenSSH is unavailable on a target system, TS remote execution should fail
closed with a clear unsupported message. The stable Python runtime remains the
production SSH implementation until TS remote execution passes policy, HITL,
audit, remote command guard, and harness parity.
