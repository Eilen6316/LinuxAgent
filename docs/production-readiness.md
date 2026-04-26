# Production Readiness Checklist

LinuxAgent v4.0.0 is ready for controlled operator-in-the-loop use. It should
not be treated as an autonomous production remediator.

## Suitable Uses

- Interactive diagnostics on development, staging, and controlled production
  hosts.
- Read-heavy operations such as service status, ports, disk usage, logs, load,
  and container inspection.
- SSH fan-out when hosts are already trusted in `known_hosts`.
- Audited troubleshooting where an operator approves each sensitive step.
- Teams that can review and tune policy rules before broader rollout.

## Not Suitable Without Additional Controls

- Fully autonomous remediation.
- Running as root by default.
- Unattended cron or CI jobs that expect confirmations to pass.
- Environments where command output cannot leave the host and no local-only
  model path is configured.
- Unknown SSH hosts or ephemeral hosts without host-key enrollment.
- Multi-tenant terminals where local users are not trusted.

## Pre-Production Checklist

- [ ] Python 3.11 or 3.12 is installed.
- [ ] `config.yaml` is owned by the operator and `chmod 600`.
- [ ] API provider, model, base URL, and timeout are explicitly reviewed.
- [ ] Runtime policy overrides are reviewed for your environment.
- [ ] SSH targets are registered in `~/.ssh/known_hosts`.
- [ ] Audit log path is on durable local storage.
- [ ] `linuxagent audit verify` is part of incident review practice.
- [ ] Operators understand that `--yes` does not bypass command-level approval.
- [ ] High-impact workflows are encoded as YAML runbooks and covered by harness
      scenarios.
- [ ] `make verify-build` passes for the release artifact you deploy.

## Release Verification

For a source checkout:

```bash
make lint
make type
make test
make security
make harness
make verify-build
```

For an installed wheel:

```bash
linuxagent --help
linuxagent check
linuxagent audit verify
```

## Operational Guardrails

- Prefer read-only prompts for the first rollout.
- Start with a small host group before enabling cluster operations broadly.
- Keep batch confirmation threshold low for production.
- Review `matched_rule`, `risk_score`, and `capabilities` during approvals.
- Treat blocked commands as policy feedback, not as failures to work around.

## Known Limitations

- Audit logs are local files; ship them to your own log pipeline if centralized
  retention is required.
- The project does not sandbox commands after approval.
- LLM analysis can be wrong; it is a summary aid, not the source of truth.
- The Anthropic provider is optional and requires the extra dependency.
- Windows is not supported.
