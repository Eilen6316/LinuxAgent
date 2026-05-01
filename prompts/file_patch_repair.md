Original user request:
{original_request}

Previous FilePatchPlan JSON:
{previous_plan}

Patch failure:
{failure_context}

The previous FilePatchPlan failed to apply. Use available read-only workspace
tools such as `read_file`, `list_dir`, and `search_files` to inspect the current
target file content before responding. If a tool says a path is a directory,
use `list_dir` on that path and read the actual target file from the previous
plan's `files_changed` or diff `+++` header.

If the current file snapshot already satisfies the original user request, return
only a JSON NoChangePlan object and do not force a patch:

```json
{{
  "plan_type": "no_change",
  "answer": "short explanation in the user's language saying the current file already satisfies the request",
  "reason": "what existing capability matched the request"
}}
```

If the original request depends on runtime command output, generated timestamps,
text-processing command output, or explicitly asks to use command execution for
the file mutation, return a JSON CommandPlan instead of another FilePatchPlan.
Use argv-safe commands only. For example, use `python3 -c` with `pathlib` and
`subprocess.run(["date"], capture_output=True, text=True, check=True)` to fetch
`date` output and update the file; do not use shell redirects, pipes, heredocs,
command substitution, or command chaining. The CommandPlan will still go through
policy, HITL confirmation, execution, and audit.

Otherwise return only a corrected JSON FilePatchPlan object. Do not return
markdown, prose, or raw shell commands. Use exactly this top-level shape:

```json
{{
  "plan_type": "file_patch",
  "goal": "short file mutation goal",
  "request_intent": "update",
  "files_changed": ["path/to/file"],
  "unified_diff": "--- path/to/file\n+++ path/to/file\n@@ -1,1 +1,2 @@\n existing line\n+new line\n",
  "risk_summary": "short risk summary",
  "verification_commands": ["string command only"],
  "permission_changes": [],
  "rollback_diff": "",
  "expected_side_effects": ["filesystem.write"]
}}
```

Do not use `--- /dev/null` for a target file that already exists. If the
original request asked to create a new file and the chosen filename is already
taken, inspect the sibling directory with `list_dir` and return a create diff
for a clear unused filename in that same directory. Do not update, overwrite, or
rewrite the existing file unless the original request asked to edit/update that
file. If the current file snapshot is present in the failure context and the
user asked to update that existing file, base the hunk context on that snapshot.
If the failure mentions `expected=...` and `actual=...`, the previous hunk
context is stale: use the `actual` line and the current snapshot as the source
of truth, then return a new diff whose context lines exactly match the current
file.
When repairing an edit to an existing file, compare the request with the current
snapshot first. Preserve existing structure, language, comments, and working
logic, and return the smallest corrected diff that adds only the missing
behavior. Do not rewrite, reformat, renumber, or translate unrelated content
just because the previous patch failed.
