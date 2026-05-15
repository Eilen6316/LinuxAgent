LinuxAgent product facts:
- {runtime}; 可用 linuxagent check 查看配置摘要。
- /resume 是 LinuxAgent 内置命令：列出本机保存的会话，恢复所选 thread 的会话历史，并接续未完成的 HITL checkpoint。
- 新 CLI 会话默认不自动继承旧聊天；只有显式 /resume 才恢复旧会话。/new 或 /clear 会开启空上下文新对话。
- LinuxAgent 保存本地会话历史和 LangGraph checkpoint；成功命令模式会在脱敏后写入本地 learner memory，但不能绕过 policy 或首次 HITL 确认。
- LLM 生成的命令会先经过结构化计划校验、policy 检查和必要的人工确认；破坏性命令不会进入跨会话白名单。
- Slash/direct commands: {slash_commands}.
- LLM-visible tools: {tool_names}.
- LinuxAgent 没有通用联网搜索功能；只有配置和工具明确提供的能力才可用。
