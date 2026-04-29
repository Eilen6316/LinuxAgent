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

Return only a corrected JSON FilePatchPlan object. Do not return a CommandPlan,
markdown, prose, or shell commands. Use exactly this top-level shape:

```json
{{
  "plan_type": "file_patch",
  "goal": "short file mutation goal",
  "files_changed": ["path/to/file"],
  "unified_diff": "--- path/to/file\n+++ path/to/file\n@@ -1,1 +1,2 @@\n existing line\n+new line\n",
  "risk_summary": "short risk summary",
  "verification_commands": ["string command only"],
  "permission_changes": [],
  "rollback_diff": "",
  "expected_side_effects": ["filesystem.write"]
}}
```

Do not use `--- /dev/null` for a target file that already exists; generate an
update diff against the existing file. If the current file snapshot is present
in the failure context, base the hunk context on that snapshot.
