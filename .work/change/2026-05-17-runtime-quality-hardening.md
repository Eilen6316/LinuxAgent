# Runtime quality hardening before Plan 9

## Context

External review identified several maintainability and operational concerns that
are adjacent to, but not part of, Plan 9 exec policy matching:

- audit hash-chain appends are thread-safe but not process-safe
- SSH async wrapping creates a short-lived executor for every call
- plan parser helpers duplicate the same strict JSON parsing flow
- `intelligence/` overstates a lightweight usage/semantic helper package
- UI prompt-toolkit selectors have lower direct unit coverage
- Anthropic provider compatibility is intentionally optional but should remain
  explicit in local docs/tests

## Decision

Insert a small maintenance pass before Plan 9 implementation. This pass may
touch audit, SSH cluster execution, parser helpers, usage-insight naming,
provider tests/docs, and focused UI tests. It must not implement Plan 9 policy
matching semantics.

## Notes

- Keep runtime config key `intelligence` stable for user compatibility.
- Rename the internal package to `usage_insights` and keep
  `linuxagent.intelligence` as a compatibility re-export.
- Preserve user-facing behavior unless the change closes an operational race or
  removes avoidable overhead.
