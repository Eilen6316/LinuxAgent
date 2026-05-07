# Red Team Baseline

LinuxAgent treats adversarial command-policy tests as a public engineering
artifact, not as a marketing score. The red-team suite records both protected
cases and known gaps so parser and policy work can be measured over time.

Run it locally:

```bash
make red-team
```

## Result Labels

| Label | Meaning |
|---|---|
| `blocked` | Policy returned `BLOCK`. The command must not execute. |
| `confirm` | Policy returned `CONFIRM`. Human approval is still required before execution. |
| `safe` | Policy returned `SAFE`. For LLM-generated commands, first execution still requires HITL through `LLM_FIRST_RUN`. |
| `xfail` | Known policy gap. This is not a protected result and must not be counted as blocked. |

`xfail` entries are strict. When a future policy change starts blocking or
confirming one of those cases, CI fails with XPASS so the baseline has to be
updated deliberately.

## Initial Coverage

The initial corpus covers at least these families:

- network-to-shell pipelines such as `curl ... | bash`
- command substitution and backticks
- `sh -c` / `bash -c` nested command strings
- interpreter escapes through Python, Perl, Node, and Awk
- `find -exec`, `find -delete`, and `xargs`
- redirects to sensitive paths
- editor and pager escape surfaces
- sensitive path reads and block-device mutation

LOLBin rules are deterministic policy checks for binaries that can execute
other commands or escape into a shell. A LOLBin hit is reported with a
`LOLBIN_*` matched rule and a capability such as `interpreter.escape`,
`shell.remote_execute`, or `lolbin.find_exec`. These rules complement shell
structure analysis; they are not a replacement for parsing and they never
downgrade an existing `BLOCK`.

The current suite also includes a minimal property-based fuzz test: arbitrary
command text must not crash the policy engine, and structural validation
failures must become explicit safety decisions.

## Interpreting The Baseline

Red-team numbers should be read as an engineering baseline:

- `BLOCK` and `CONFIRM` show the current deterministic policy response.
- `xfail` is an acknowledged risk queued for later parser or policy work.
- The suite is expected to become stricter as parser coverage improves.

Do not present the xfail count as protected coverage.
