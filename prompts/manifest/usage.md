# usage

LinuxAgent supports natural-language Linux operations requests, direct shell commands prefixed by
`!`, and slash commands such as `/help`, `/tools`, `/trace`, `/resume`, `/job`, `/new`, `/clear`,
`/exit`, and `/quit`. `/job` lists background jobs, `/job status` shows the background job runtime
health, `/job daemon` shows daemon lifecycle guidance, `/job daemon install` writes a systemd user
unit file, `/job <job_id>` shows one job's status/output, `/job follow <job_id>` follows updates in
the current CLI, and `/job stop <job_id>` requests cancellation. With the local job daemon enabled,
approved background jobs run in the daemon supervisor and remain inspectable through the same `/job`
entry point. Help text must describe the same command catalog used by completion.

Natural-language operational requests are planned as validated `CommandPlan`
JSON before policy, HITL, execution, and analysis. File creation or edit
requests are planned as validated `FilePatchPlan` JSON, previewed as diffs, and
applied transactionally after approval. The planner may use read-only workspace
inspection tools, log search, system information tools, configured YAML runbook
guidance, optional Skill manifest guidance, optional usage-insight tools, and
optional bounded `fetch_url` reads when network policy enables that tool. SSH
cluster fan-out, local background jobs, session checkpoints, `/resume`, audit
inspection, and MCP read-only policy/audit tools are product entry points, not
hidden autonomous powers.

When a request lacks several concrete parameters needed for safe planning, LinuxAgent can open an
automatic parameter-collection wizard. This is AI-discovered from the user's natural-language
request, not a user-invoked explicit command. Pending wizard sessions appear in `/resume`, and recovered
sessions continue from the latest stable checkpoint rather than from every transient keypress.
