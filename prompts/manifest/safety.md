# safety

LinuxAgent treats LLM output as untrusted. Model-generated commands are validated, policy-checked,
and confirmed by a human when required. Destructive commands never enter a cross-session whitelist.
Human decisions and command outcomes are recorded in the audit log.
