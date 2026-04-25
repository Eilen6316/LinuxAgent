# .work/ · 任务协作目录

本目录是 AI agent（Claude Code、Codex 等）与人类开发者之间的**共享工作区**。

## 目录职责

| 目录        | 职责                                                    | 读写规则                         |
| --------- | ----------------------------------------------------- | ---------------------------- |
| `design/` | 架构决策记录（ADR），含动机与被否决的方案                                | 只读，不要改写；新的设计记录走 `change/`    |
| `prompt/` | 预留目录（兼容早期文档）；**不作为运行时 Prompt 真源**                    | 不在此放运行时 Prompt；如需启用先走 `change/` |
| `plan/`   | 按轮次拆分的实现计划：**仅 scope / 验收 / 交付物**，不重复全局规则             | 完成后在末尾追加「完成记录」并更新本 README    |
| `rule/`   | 项目级编码约定（`baseline.md` + `python.md` 已就位）                     | 可增不可删，删除需走 `change/`         |
| `change/` | 变更记录（设计变更、参数调整、偏离计划等）                                 | 仅追加，不修改历史条目                  |

## 单一真源原则

- 运行时 Prompt 模板的唯一真源是仓库根 `prompts/`；`.work/prompt/` 仅作兼容占位
- Plan 文件**不复述** `prompts/` 的模板内容或 `configs/default.yaml` 的默认值，只引用对应文件/章节
- 代码约定放 `rule/`，不要写进 plan
- 偏离任何权威文档前，先在 `change/` 起一条记录
- 同一主题若存在多条 `change/` 记录且内容冲突，以**日期更新者**为准

## 建议的协作节奏

1. **接到任务** → 读 `rule/baseline.md` + 对应 `plan/PlanN.md`
2. **遇到决策分歧** → 查 `design/` 中对应的 ADR
3. **发现需要偏离计划** → 先在 `change/` 写一条变更说明，再改代码
4. **完成一轮** → 在对应 Plan 文件末尾追加「完成记录」（日期、commit hash、偏差项）

## 当前状态

- [x] 架构设计就绪（`design/architecture.md`）—— LangGraph + 分层 + DI
- [x] 编码规则就绪（`rule/baseline.md` + `rule/python.md`）
- [x] 第一阶段重写完成（Plan1–Plan6）
- [x] UI + Harness + CI + 本地 build / wheel verify 闭环已打通
- [x] Plan 7：隐私脱敏与输出保护
- [x] Plan 8：能力驱动的策略引擎
- [x] Plan 9：结构化 CommandPlan 与 Runbook
- [ ] Plan 10：可观测性与防篡改审计

## 技术栈总览

- **Agent 编排**：LangGraph（状态机 + checkpointing）
- **LLM 抽象**：LangChain Core（Messages / Tools / PromptTemplate）
- **配置**：Pydantic v2（fail-fast 验证）
- **重试**：tenacity（指数退避）
- **语义检索**：LLM Embedding API（经 `langchain-openai` 调用远端 embedding，不引入本地模型）
- **测试 Harness**：YAML 场景驱动 + LangSmith 追踪（可选）

## 目录布局

采用 PyPA 推荐的 **src-layout** + 领域导向子包 + 资源外置。完整树见 `design/architecture.md` §目录结构。顶层：

```
LinuxAgent/
├── src/linuxagent/     ← 唯一发布包
├── tests/              ← unit / integration / harness
├── prompts/            ← Prompt 模板
├── configs/            ← 配置样例
├── docs/               ← 用户与开发文档
├── scripts/            ← bootstrap / release
├── .github/workflows/  ← CI/CD
├── pyproject.toml      ← PEP 517/621 单一真源
├── Makefile            ← make test / lint / harness
└── config.yaml         ← 用户本地配置（chmod 600，gitignore；含密钥）
```
