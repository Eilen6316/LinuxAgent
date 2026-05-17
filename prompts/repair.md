Original user request:
{original_request}

Current goal:
{current_goal}

Failed command results:
{failure_context}

The previous plan did not complete successfully. Return only a JSON CommandPlan
with the next recovery commands needed to finish the original request. Do not
end with analysis. Do not repeat failed commands unless you changed the command.
Do not repeat commands listed as already successful; only repair or continue the
failed or still-missing part of the original request.
Each command string is parsed with `shlex` and executed as an argv list without
a shell. Do not chain OS commands with `||`, `&&`, pipes, redirects,
environment assignment prefixes, shell redirections like `2>&1`, or command
substitution; put fallbacks in separate command steps. Prefer non-interactive
administration commands over terminal clients. For process inspection, choose
the narrowest process query that captures the requested fields and scope; avoid
broad process listings when a focused query will answer the question.
