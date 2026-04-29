Original user request:
{original_request}

Previous FilePatchPlan JSON:
{previous_plan}

Patch failure:
{failure_context}

The previous FilePatchPlan failed to apply. Use available read-only workspace
tools such as `read_file`, `list_dir`, and `search_files` to inspect the current
target file content before responding. Return only a corrected JSON FilePatchPlan
object. Do not return a CommandPlan. Do not use `--- /dev/null` for a target
file that already exists; generate an update diff against the existing file.
