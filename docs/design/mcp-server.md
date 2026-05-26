# MCP Server Design

Status: configurable read-only stdio server.

## Goal

LinuxAgent can expose selected safety primitives to local MCP clients without
turning the project into an unattended command runner. The initial transport is
stdio only, which matches local MCP client usage and avoids remote endpoint
authentication, multi-tenant state, and network exposure.

This design follows the MCP tool model: the server declares a `tools`
capability, clients discover tools with `tools/list`, and clients invoke tools
with `tools/call`.

It also exposes bounded read-only resources for public capability summaries.
Resources are not execution handles.

## Threat Model

An MCP client is model-facing software. Tool calls may be triggered by model
context, prompt injection, or user confusion, so LinuxAgent must assume tool
inputs are untrusted.

The server therefore exposes only read-only capabilities:

- `linuxagent.policy.classify`
- `linuxagent.audit.verify`

It does not expose command execution, file patch application, SSH fan-out, or
secrets. A malicious MCP client can ask whether a command would be blocked, but
it cannot cause LinuxAgent to execute that command through the MCP server.

## Configuration

MCP is configured through `config.yaml`:

```yaml
mcp:
  enabled: true
  transport: stdio
  tools:
    - linuxagent.policy.classify
    - linuxagent.audit.verify
  resources:
    - linuxagent://skills/summary
    - linuxagent://memory/summary
```

`transport` currently accepts only `stdio`. `tools` and `resources` are explicit
allowlists: unknown names fail config validation, and entries omitted from the
list are not returned by list methods or callable/readable by clients.

The default config enables the stdio server with both read-only tools. Setting
`mcp.enabled: false` makes `linuxagent mcp` fail closed instead of starting a
server.

## Exposed Tools

| Tool | Behavior | State mutation |
|---|---|---|
| `linuxagent.policy.classify` | Runs the configured policy engine against a command and source | None |
| `linuxagent.audit.verify` | Verifies the configured audit log hash chain | None |

Policy classification returns `SAFE`, `CONFIRM`, or `BLOCK`, plus risk score,
capabilities, matched rules, approval requirement, and whitelist eligibility.
Audit verification returns validity, record count, tamper line, reason, and the
configured audit path.

## Exposed Resources

| Resource | Behavior | State mutation |
|---|---|---|
| `linuxagent://skills/summary` | Returns Skill name/version/description/permissions/guidance presence | None |
| `linuxagent://memory/summary` | Returns opt-in advisory memory summary metadata when memory is enabled | None |

Resources intentionally return summaries. They do not expose command strings,
planner guidance bodies, execution results, raw audit logs, config secrets, or
filesystem content. The memory summary is advisory model context only; it cannot
alter policy, HITL, sandbox, execution, or audit behavior.

## Non-Exposed Capabilities

These remain intentionally unavailable over MCP:

- arbitrary command execution without HITL
- privileged command execution
- file patch application
- SSH cluster execution
- raw audit record search
- full Skill planner guidance export
- raw secrets, provider keys, config values, or environment values

If execution is added later, it must call the same graph/service path as the
CLI so `CommandPlan` validation, deterministic policy, HITL interrupt, sandbox
metadata, audit, and telemetry all remain intact. A direct executor tool is not
acceptable.

## Client Responsibility Boundary

The MCP client is responsible for:

- showing the operator which tools are exposed
- showing tool inputs before model-triggered calls
- applying client-side confirmation for sensitive operations
- applying request timeouts
- treating returned structured content as untrusted model context

LinuxAgent is responsible for:

- validating JSON-RPC request shape and tool arguments
- keeping the server local stdio only
- redacting structured tool output
- never exposing command execution in this server
- reusing existing policy and audit verifier logic

## Protocol Surface

The server supports:

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`
- `resources/list`
- `resources/read`
- `shutdown`

Unknown methods, tools, and resources return JSON-RPC errors. Business
validation failures inside a known tool return a tool result with
`isError: true`.

## Future Slices

1. Add an audit summary tool that returns bounded, redacted aggregates rather
   than raw audit lines.
2. Add a command proposal tool that returns a `CommandPlan` preview only.
3. Add execution only through the existing LangGraph HITL flow, with no
   background or non-interactive auto-approval path.
4. Consider Streamable HTTP only after authentication, authorization,
   rate-limiting, and deployment guidance are designed.
