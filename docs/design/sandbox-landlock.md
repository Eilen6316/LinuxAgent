# Landlock Sandbox Design

Status: design only. No runner backend is implemented in this plan.

## Goal

LinuxAgent should eventually prefer a kernel-native filesystem sandbox when it
can enforce the requested profile without extra system packages. Linux Landlock
is the first candidate because it is unprivileged, process-local, and available
on modern Linux kernels.

The default `noop` runner remains unchanged until a Landlock backend has a
tested implementation and compatibility matrix.

## Threat Boundary

Landlock can restrict filesystem access for the current process and its child
processes after rules are applied. It is useful for profiles such as
`read_only`, `workspace_write`, and `system_inspect` where LinuxAgent already
has configured allowed roots.

Landlock does not:

- sandbox remote SSH targets
- virtualize networking
- limit CPU, memory, process count, or stdout size
- protect against a compromised parent process before rules are applied
- stop a privileged local root user from changing host state outside the
  confined process model
- replace HITL, policy, audit, or least-privilege OS accounts

## Capability Detection

The runner should probe capability at startup and before first use:

- platform is Linux
- kernel exposes the Landlock syscall ABI
- supported ABI version is high enough for the intended access rights
- current process can create a ruleset and restrict itself
- every configured `sandbox.allowed_roots` entry exists or can be explicitly
  rejected before execution
- requested network policy is either `inherit` or handled by another layer

The probe result should be audit-visible: `runner=landlock`, `enabled=true`,
`enforced=true|false`, `fallback_reason=<reason>`.

## Compatibility Matrix

| Environment | Expected behavior |
|---|---|
| Linux kernel before 5.13 | Landlock unavailable; fallback chain applies |
| Linux 5.13+ bare metal / VM | Probe ABI, then enforce filesystem rules if supported |
| Debian/Ubuntu/RHEL/Fedora/SUSE with kernel 5.13+ | Treat distribution support as kernel-and-policy dependent; probe the running host instead of trusting distro names |
| Container without Landlock syscall access | Treat as unavailable; fallback chain applies |
| Container with seccomp blocking Landlock syscalls | Treat as unavailable; fallback chain applies |
| Non-Linux | Landlock unavailable; fallback chain applies |
| Rootless user | Expected supported path; Landlock is designed for unprivileged use |
| Privileged local root | Landlock is not the primary boundary; audit and deployment controls still matter |

## Fallback Chain

When a safe profile requires enforcement:

1. `landlock` if configured or auto-selected and probe succeeds
2. `bubblewrap` if configured/available and can enforce the requested profile
3. fail closed with a clear warning if no enforcing backend is available

When sandbox is disabled or the requested profile is `none`, LinuxAgent may
continue with `noop` metadata only and an explicit noop warning. `noop` must
never claim `enforced=true`.

The future runner selection can use:

```text
configured runner == landlock -> landlock only, fail closed if unavailable
configured runner == bubblewrap -> bubblewrap only, fail closed if unavailable
configured runner == local/noop -> current behavior
configured runner == auto -> landlock -> bubblewrap -> fail closed for safe profiles
```

`auto` is intentionally a future option. This plan does not add it to config.

## Filesystem Rule Mapping

Landlock rules should be derived from the existing sandbox request:

| Sandbox profile | Landlock filesystem rules |
|---|---|
| `read_only` | read-only access to `allowed_roots`; no write rights |
| `system_inspect` | read-only `allowed_roots` plus explicit read access for approved system inspection paths |
| `workspace_write` | read access to `allowed_roots`; write/create/remove rights only below workspace roots |
| `privileged_passthrough` | no Landlock enforcement; audit must show passthrough |
| `none` | no Landlock enforcement |

Path handling requirements:

- resolve configured roots before creating rules
- reject missing roots for safe profiles unless the profile explicitly allows
  creating a workspace root
- reject symlink escapes by resolving final canonical paths
- record allowed roots in sandbox audit metadata
- avoid broad `/` read access unless a profile explicitly requires it and the
  user configured it

## Network And Seccomp

Landlock does not provide network isolation. Existing network policy values
should be interpreted as:

| Network policy | Landlock-only behavior |
|---|---|
| `inherit` | allowed |
| `disabled` | unsupported by Landlock alone; require another backend or fail closed |
| `loopback_only` | unsupported by Landlock alone; require another backend or fail closed |
| `allowlist` | unsupported by Landlock alone; require another backend or fail closed |

Seccomp-bpf can complement Landlock later for syscall and network-adjacent
controls, but it should be a separate design and implementation plan. This plan
does not add seccomp.

## Warning And Failure Policy

Safe profiles must fail closed when the selected runner cannot enforce the
requested boundary. The error should include:

- selected runner
- requested profile
- failed capability check
- suggested fallback (`bubblewrap`) or configuration change

Compatibility profiles may continue with `noop` only when the user explicitly
configured disabled/noop behavior. The UI and audit record must make
`enforced=false` visible.

## Test Matrix

Minimum tests for a future Landlock backend:

| Test | Expected result |
|---|---|
| Probe on unsupported kernel | unavailable reason, no crash |
| Read allowed file under `read_only` | succeeds |
| Write under `read_only` | fails before or during execution |
| Write under `workspace_write` inside workspace | succeeds |
| Write under `workspace_write` outside workspace | fails |
| Command with `network: disabled` under Landlock-only | fail closed |
| Missing allowed root for safe profile | fail closed |
| Symlink from allowed root to `/etc/shadow` | denied |
| Bubblewrap fallback when Landlock unavailable | uses bubblewrap if configured and available |
| Noop fallback for disabled sandbox | metadata shows `enforced=false` |

Minimum local commands:

```bash
make sandbox
make security
make test
```

Future CI should add an optional Linux job that runs Landlock-specific tests only
when the kernel and container allow the required syscalls.

## Implementation Slices

1. Add `SandboxRunnerKind.LANDLOCK` and config parsing.
2. Implement capability probe and audit-visible result object.
3. Implement read-only rules for a minimal `read_only` profile.
4. Add `workspace_write` create/write/remove rules.
5. Add fallback selection only after direct runner behavior is stable.
6. Add optional CI coverage for Landlock-enabled runners.

This order keeps the current stable `noop`, `local`, and `bubblewrap` paths
unchanged while the kernel backend is developed.
