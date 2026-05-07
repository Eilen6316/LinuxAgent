# MCP Server Design

Status: minimal read-only prototype.

## Goal

LinuxAgent can expose selected safety primitives to local MCP clients without
turning the project into an unattended command runner. The initial transport is
stdio only, which matches local MCP client usage and avoids remote endpoint
authentication, multi-tenant state, and network exposure.

This design follows the MCP tool model: the server declares a `tools`
capability, clients discover tools with `tools/list`, and clients invoke tools
with `tools/call`.

## Threat Model

An MCP client is model-facing software. Tool calls may be triggered by model
context, prompt injection, or user confusion, so LinuxAgent must assume tool
inputs are untrusted.

The current prototype therefore exposes only read-only capabilities:

- `linuxagent.policy.classify`
- `linuxagent.audit.verify`

It does not expose command execution, file patch application, SSH fan-out, or
secrets. A malicious MCP client can ask whether a command would be blocked, but
it cannot cause LinuxAgent to execute that command through the MCP server.

## Exposed Tools

| Tool | Behavior | State mutation |
|---|---|---|
| `linuxagent.policy.classify` | Runs the configured policy engine against a command and source | None |
| `linuxagent.audit.verify` | Verifies the configured audit log hash chain | None |

Policy classification returns `SAFE`, `CONFIRM`, or `BLOCK`, plus risk score,
capabilities, matched rules, approval requirement, and whitelist eligibility.
Audit verification returns validity, record count, tamper line, reason, and the
configured audit path.

## Non-Exposed Capabilities

These remain intentionally unavailable over MCP:

- arbitrary command execution without HITL
- privileged command execution
- file patch application
- SSH cluster execution
- raw audit record search
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
- never exposing command execution in this prototype
- reusing existing policy and audit verifier logic

## Protocol Surface

The prototype supports:

- `initialize`
- `notifications/initialized`
- `tools/list`
- `tools/call`
- `shutdown`

Unknown methods and unknown tools return JSON-RPC errors. Business validation
failures inside a known tool return a tool result with `isError: true`.

## Future Slices

1. Add MCP resources for redacted runbook summaries.
2. Add an audit summary tool that returns bounded, redacted aggregates rather
   than raw audit lines.
3. Add a command proposal tool that returns a `CommandPlan` preview only.
4. Add execution only through the existing LangGraph HITL flow, with no
   background or non-interactive auto-approval path.
5. Consider Streamable HTTP only after authentication, authorization,
   rate-limiting, and deployment guidance are designed.
