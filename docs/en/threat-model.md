# Threat Model

LinuxAgent is a local CLI that can ask an LLM to propose Linux operations and
then execute approved commands. The main design goal is not to sandbox Linux,
but to make model-driven operations explicit, reviewable, and auditable.

## Assets

- Local and remote system integrity.
- API keys and credentials in `config.yaml`.
- Command output, logs, hostnames, usernames, IPs, paths, and production data.
- SSH private keys and `known_hosts` trust decisions.
- Audit log integrity at `~/.linuxagent/audit.log`.
- Operator intent and approval decisions.

## Trust Boundaries

| Boundary | Trust assumption |
|---|---|
| User terminal | The local operator is trusted to approve or deny commands |
| LLM provider | Not trusted with secrets or final authority |
| Local subprocess | Executes with the invoking user's privileges; the Plan 1 no-op sandbox records metadata only |
| SSH target | Must already be trusted through `known_hosts` |
| Config file | Trusted only if owned by the user and `chmod 600` |
| Audit log | Append-only best effort with hash-chain tamper detection |

## Primary Threats and Mitigations

| Threat | Mitigation |
|---|---|
| Prompt injection produces a dangerous command | Token-level policy engine, source-aware `LLM_FIRST_RUN`, destructive commands require confirmation |
| User accidentally approves broad batch execution | Batch confirmation for host count greater than or equal to the configured threshold |
| LLM output bypasses safety through quoting or shell syntax | `shlex` token facts plus raw embedded-danger checks |
| Remote command expands unexpectedly through shell features | SSH cluster mode rejects shell chaining, redirects, command substitution, and variable expansion |
| Unknown SSH host enables MITM | `RejectPolicy` and `load_system_host_keys()` by default |
| Secrets leak through logs or command output | `SecretStr`, config permission checks, output guard, redaction before LLM-facing analysis paths |
| Audit log tampering hides an approval | Hash-chained JSONL records and `linuxagent audit verify` |
| Non-interactive automation silently approves work | No-TTY confirmation requests auto-deny |
| Overly broad dependencies increase supply-chain risk | Major-version bounds plus release constraints file and build verification |
| Operators assume sandbox isolation is active | `sandbox.enabled=true` is rejected while only the no-op runner exists; audit/telemetry marks `enforced=false` |

## Out of Scope

- Sandboxing arbitrary commands after the operator approves them. Plan 1 only
  records sandbox profile metadata; enforcing runners are future work.
- Preventing a malicious local root user from modifying files.
- Replacing host intrusion detection, EDR, SIEM, or privileged access
  management.
- Guaranteeing that LLM-generated analysis is correct.
- Protecting data after the operator intentionally sends it to an external
  provider.

## Security Review Hotspots

Changes in these areas require focused tests and careful review:

- `src/linuxagent/policy/`
- `src/linuxagent/executors/`
- `src/linuxagent/cluster/`
- `src/linuxagent/graph/`
- `src/linuxagent/security/`
- `src/linuxagent/audit.py`
- `src/linuxagent/config/`

## Operational Recommendations

- Use a dedicated low-privilege OS account for routine operations.
- Keep `config.yaml` local, owned by the operator, and `chmod 600`.
- Register SSH host keys out of band before cluster use.
- Review audit logs after high-impact sessions.
- Keep runtime policies environment-specific and test them with harness
  scenarios before production use.
