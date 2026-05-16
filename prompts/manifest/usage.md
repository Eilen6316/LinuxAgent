# usage

LinuxAgent supports natural-language Linux operations requests, direct shell commands prefixed by
`!`, and slash commands such as `/help`, `/tools`, `/trace`, `/resume`, `/job`, `/new`, `/clear`,
`/exit`, and `/quit`. `/job` lists background jobs, `/job <job_id>` shows one job's status/output,
`/job follow <job_id>` follows updates in the current CLI, and `/job stop <job_id>` requests
cancellation. Background job history is persisted locally for later inspection, but running jobs do
not continue after the LinuxAgent process exits. Help text must describe the same command catalog
used by completion.
