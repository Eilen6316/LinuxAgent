# session_resume

`/resume` is a built-in command. It lists local saved sessions, restores the selected thread's chat
history, and can continue an unfinished LangGraph HITL checkpoint for that same thread. New CLI
sessions do not automatically inherit old conversations; `/new` and `/clear` start empty context.
