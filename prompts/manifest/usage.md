# usage

LinuxAgent supports natural-language Linux operations requests, direct shell commands prefixed by
`!`, and slash commands such as `/help`, `/tools`, `/trace`, `/resume`, `/job`, `/new`, `/clear`,
`/exit`, and `/quit`. `/job` lists background jobs, `/job status` shows the background job runtime
health, `/job <job_id>` shows one job's status/output, `/job follow <job_id>` follows updates in the
current CLI, and `/job stop <job_id>` requests cancellation. With the local job daemon enabled,
approved background jobs run in the daemon supervisor and remain inspectable through the same `/job`
entry point. Help text must describe the same command catalog used by completion.
