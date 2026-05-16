# usage

LinuxAgent supports natural-language Linux operations requests, direct shell commands prefixed by
`!`, and slash commands such as `/help`, `/tools`, `/trace`, `/resume`, `/jobs`, `/job <job_id>`,
`/stop <job_id>`, `/new`, `/clear`, `/exit`, and `/quit`. `/jobs` lists in-process background
jobs started by approved long-running plans, `/job <job_id>` shows one job's status/output, and
`/stop <job_id>` requests cancellation. Help text must describe the same command catalog used by
completion.
