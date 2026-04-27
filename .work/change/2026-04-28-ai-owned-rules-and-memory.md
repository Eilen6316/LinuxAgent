# AI 判断规则与 learner memory 边界

- **日期**：2026-04-28
- **类型**：规则收紧
- **影响范围**：规则文档、策略配置、intent routing、learner memory
- **决策者**：用户

## 背景

用户要求意图分流、运维语义判断和具体操作方法不得在 Python 代码中写死，应该由模型运行时判断；成功执行的方法应脱敏后进入 learner memory，供后续推荐和相似命令检索。

## 新决策

- Python 中禁止新增业务/意图关键词表、固定运维方法答案、产品特定操作流程分支。
- 意图分流由 `prompts/intent_router.md` 的 LLM 路由决定，Python 只解析结构化协议。
- 默认安全策略数据从 `configs/policy.default.yaml` 加载；Python 只负责 Pydantic 校验、token 化、匹配和决策。
- learner memory 记录脱敏后的完整成功命令模式，不再只记录第一个 token。
- R-SEC / R-HITL 红线仍保持确定性策略，不能交给模型自由记忆或自由放行。

## 影响

- **受影响文档**：
  - `.work/rule/baseline.md`
  - `README.md`
  - `docs/en/README.md`
  - `docs/zh/README.md`
- **受影响代码**：
  - `src/linuxagent/policy/builtin_rules.py`
  - `src/linuxagent/policy/engine.py`
  - `src/linuxagent/policy/models.py`
  - `src/linuxagent/intelligence/command_learner.py`
  - `src/linuxagent/graph/intent.py`

## 是否向后兼容

是。安全策略输出保持 `SAFE` / `CONFIRM` / `BLOCK`，但规则数据改为 YAML 单一真源；learner memory 的 key 从命令头升级为脱敏后的完整命令模式。
