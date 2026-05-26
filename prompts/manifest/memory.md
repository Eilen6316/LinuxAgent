# memory

LinuxAgent stores local chat history and LangGraph checkpoints. It may also learn successful command
patterns after redaction in learner memory. Learner memory is advisory only: it cannot bypass policy,
first-use HITL confirmation, destructive-command confirmation, or audit logging.

When `memory.enabled` is true, LinuxAgent can maintain an opt-in filesystem memory under
`memory.path`. Manual `/memory add <text>` and `linuxagent memory add <text>` writes are redacted
before persistence; the generated summary can be injected into prompts as operator/project
background. This memory is advisory only and never changes command policy, sandbox enforcement,
execution approval, or audit records.

`/memory suggest` and `linuxagent memory suggest` create reviewable candidates under `pending/`
from local chat history. Candidates do not affect prompts until the operator explicitly promotes
one with `memory promote <pending-filename>`.
