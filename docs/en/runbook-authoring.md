# Runbook Authoring

Runbooks are curated operational guidance for the planner. They are not keyword
routers and they do not bypass policy. The graph injects validated runbook
summaries into the planner prompt, then every generated command still goes
through `CommandPlan` validation, policy, HITL, execution, audit, and analysis.

Built-in runbooks live in `runbooks/`.

## When To Add A Runbook

Add a runbook when a diagnostic workflow is common, repeatable, and useful as
planning guidance:

- checking disk pressure
- inspecting service state
- collecting recent logs
- locating a port owner
- reading OS or package metadata

Avoid runbooks that primarily mutate production state. Mutation commands require
stronger policy review and should usually remain model-planned with explicit
operator confirmation rather than packaged as routine guidance.

## Minimum Shape

Use existing files in `runbooks/` as the source of truth for the exact schema.
A typical read-only runbook includes:

```yaml
id: service-status
title: Service status inspection
description: Inspect a systemd service without mutating it.
steps:
  - command: systemctl status nginx --no-pager
    purpose: Show service state and recent status output.
    read_only: true
  - command: journalctl -u nginx --no-pager -n 100
    purpose: Show recent service logs.
    read_only: true
```

## Safety Rules

- Prefer read-only commands.
- Include `--no-pager` or equivalent non-interactive flags.
- Avoid shell operators, redirects, pipes, command substitution, and globbing.
- Do not include secrets, tokens, private hostnames, or private IPs.
- Use documentation IP ranges in examples: `192.0.2.0/24`,
  `198.51.100.0/24`, or `203.0.113.0/24`.
- Every `read_only: true` command must evaluate to `SAFE` under the policy
  engine during runbook loading.

## Validation

Run:

```bash
make test
make harness
make security
```

For focused validation, add or update unit tests around `RunbookEngine` and
policy evaluation. Do not mock the policy engine for safety-sensitive runbook
checks.

## Contribution Checklist

- The runbook has a clear title and operational purpose.
- Every step is deterministic and non-interactive.
- The command works without a shell pipeline.
- The command does not require root by default.
- The runbook is advisory guidance only; it does not assume auto-execution.
- Documentation or release notes mention new user-visible runbook areas.
