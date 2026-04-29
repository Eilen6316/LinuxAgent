Original user request:
{original_request}

Current goal:
{current_goal}

Failed command results:
{failure_context}

The previous plan did not complete successfully. Return only a JSON CommandPlan
with the next recovery commands needed to finish the original request. Do not
end with analysis. Do not repeat failed commands unless you changed the command.
Do not chain OS commands with `||`, `&&`, pipes, redirects, or command
substitution; put fallbacks in separate command steps. Prefer non-interactive
administration commands over terminal clients.
