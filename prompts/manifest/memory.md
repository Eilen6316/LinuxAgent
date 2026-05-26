# memory

LinuxAgent stores local chat history and LangGraph checkpoints. It may also learn successful command
patterns after redaction in learner memory. Learner memory is advisory only: it cannot bypass policy,
first-use HITL confirmation, destructive-command confirmation, or audit logging.

LinuxAgent maintains a local filesystem memory under `memory.path` by default. The generated
summary can be injected into prompts as operator/project background. This memory is advisory only
and never changes command policy, sandbox enforcement, execution approval, or audit records.

When `auto_consolidate_on_startup` is true, chat startup automatically runs a local deterministic
two-stage pipeline: stage1 writes redacted history records under `stage1/`, and stage2 refreshes
`raw_memories.md` plus `memory_summary.md`. It performs no shell execution, network calls, or LLM
calls. `linuxagent memory ...` is a maintenance/debug CLI for inspecting, suggesting, promoting,
or manually adding notes; it is not the runtime memory trigger.
