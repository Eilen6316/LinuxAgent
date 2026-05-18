# tools

LLM-visible tools are registered through the tool catalog and must carry `ToolSandboxSpec` metadata.
Tool metadata describes sandbox profile, file access, command execution, network access, HITL mode,
allowed roots, timeouts, and output budgets. Missing or invalid metadata must be denied before the
tool runs.

Direct URL fetch is available only when application network policy is explicitly enabled in
configuration. The `fetch_url` tool is read-only, supports HTTP/HTTPS GET or HEAD, follows bounded
redirects, and applies domain policy plus SSRF checks before every request and redirect hop. It is
not a web search or browser tool.
