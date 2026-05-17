# 开发

## 架构稳定性预算

`make security` 和 CI 会运行 `scripts/check_architecture_budget.py`。这个门禁把
架构稳定化工作变成可执行约束：

- `src/linuxagent/app/agent.py` 保持 300 个物理行以内。
- `graph/` 模块默认保持 430 个物理行以内。当前仍偏大的模块使用窄范围单文件上限，
  只锁住现状；继续增长时需要先拆分。
- 安全敏感的 `plans/` 模块默认保持 260 个物理行以内，现有公开计划模型门面有单文件上限。
- 所有 Python 函数保持 50 个物理行以内。
- 新增 `AgentState` 字段必须同步写入 `graph/state_contracts.py` 的所有权分区。
- 新增 graph node factory 必须加入预算覆盖清单，并指向真实的单元测试和 harness 或边界场景。

LLM 可见工具的 `ToolSandboxSpec` 元数据、以及 subprocess 只能由 sandbox runner 拥有，
由同一个 security gate 中的 `scripts/check_sandbox_rules.py` 继续强制检查。
