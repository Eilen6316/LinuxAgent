# Policy Benchmark

Generated: 2026-05-07 21:02:59 +0800

## Environment

- Python: 3.12.12
- Platform: Linux-5.14.0-427.42.1.el9_4.x86_64-x86_64-with-glibc2.34
- Iterations per command: 250

## Results

| Case | Commands | P50 ms | P95 ms | P99 ms |
|---|---:|---:|---:|---:|
| simple commands | 1000 | 0.282 | 0.395 | 0.456 |
| shell structure | 1000 | 0.661 | 1.234 | 1.344 |
| red-team corpus | 1750 | 0.403 | 1.269 | 1.411 |

## Interpretation

The benchmark measures deterministic policy classification only. It excludes
LLM provider calls, terminal rendering, audit writes, sandbox startup, and
actual command execution.

Mean P99 across benchmark groups: 1.070 ms.
