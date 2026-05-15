# memory

LinuxAgent stores local chat history and LangGraph checkpoints. It may also learn successful command
patterns after redaction in learner memory. Learner memory is advisory only: it cannot bypass policy,
first-use HITL confirmation, destructive-command confirmation, or audit logging.
