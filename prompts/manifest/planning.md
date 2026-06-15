# planning

The intent router chooses one of five routes: `DIRECT_ANSWER` (conversation, product, or capability
questions), `CLARIFY` (one safety-critical question), `WIZARD_NEEDED` and `REQUEST_USER_INPUT`
(structured discovery of several missing inputs), and `COMMAND_PLAN` (operational work). Operational
work must become structured `CommandPlan` or `FilePatchPlan` JSON before policy, HITL, or file
mutation. Conversational, product, or capability questions stay on the direct-answer path.
