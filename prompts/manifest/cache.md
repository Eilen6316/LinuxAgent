# cache

LinuxAgent has provider-side prompt cache support, not local command-result caching.
When `api.prompt_cache` is enabled, the runtime sends a stable per-thread
`prompt_cache_key` to compatible providers. Providers that support it may report
cached input tokens; LinuxAgent records that usage in `llm.usage` telemetry with
the prompt cache key attributes. If a backend rejects `prompt_cache_key`,
LinuxAgent retries without it and disables the cache key for that provider
instance.

Anthropic-compatible providers use Anthropic message cache control breakpoints
instead of `prompt_cache_key`. Runtime usage summaries are visible through
`/tools` when the configured provider reports token usage metadata.

LinuxAgent does not cache shell command results, tool stdout/stderr, file reads,
or system inspection results to skip execution. Repeated commands and tool calls
still execute again and remain behind policy, sandbox metadata, HITL gates, and
redaction.
