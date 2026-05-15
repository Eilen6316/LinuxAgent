# tools

LLM-visible tools are registered through the tool catalog and must carry `ToolSandboxSpec` metadata.
Tool metadata describes sandbox profile, file access, command execution, network access, HITL mode,
allowed roots, timeouts, and output budgets. Missing or invalid metadata must be denied before the
tool runs.
