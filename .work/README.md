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
- [x] v4 基线能力完成：policy / HITL / audit / CommandPlan / FilePatchPlan / Runbook / SSH host-key 校验
- [x] v4.0.0 正式发布完成：GitHub Release + PyPI `linuxagent==4.0.0`
- [x] 安全深度专项旧 Plan 1-8 已完成，计划文件已从 `.work/plan/` 移除
- [x] MCP / Skill 配置化专项已完成（旧 Plan 1-3：`28b460f` / `6e1577f` / `a145d9f`）
- [x] Plan 1：Release hardening（DeepSeek-TUI 借鉴专项，参考路径 `/DeepSeek-TUI`）
- [x] Plan 2：Audit inspect diagnostics（DeepSeek-TUI 借鉴专项）
- [x] Plan 3：Runtime stdout capture and analyzer trust chain（线上 BUG 修复，优先）
- [x] Plan 4：Inline interpreter policy visibility（线上 BUG 修复，优先）
- [x] Plan 5：Command reviewability and planner command shape（HITL 质量修复，优先）
- [x] Plan 6：CLI confirmation and tool-noise cleanup（CLI 体验修复，优先；确认 UI 子项按用户限制延期）
- [x] Plan 7：Tool metadata and runtime gate（DeepSeek-TUI 借鉴专项）
- [x] Plan 8：Tool execution budget and runtime events（DeepSeek-TUI 借鉴专项）
- [x] Plan 9：Exec policy arity-aware matching（DeepSeek-TUI 借鉴专项，核心安全能力）
- [x] Plan 10：Network policy foundation（DeepSeek-TUI 借鉴专项）
- [x] Plan 11：Network fetch SSRF guard（DeepSeek-TUI 借鉴专项）
- [x] Plan 12：Remote Skill package verifier dry-run index（索引已完成，不作为执行项；下一项 Plan 12a）
- [ ] Plan 12a：Remote Skill local archive verifier dry-run（DeepSeek-TUI 借鉴专项，供应链安全）
- [ ] Plan 12b：Remote Skill safe fetch integration（DeepSeek-TUI 借鉴专项，供应链安全）
- [ ] Plan 12c：Remote Skill verify report and CLI（DeepSeek-TUI 借鉴专项，供应链安全）
- [ ] Plan 13：Remote Skill staging install（DeepSeek-TUI 借鉴专项，供应链安全）
- [ ] Plan 14：Skill trust and activation workflow（DeepSeek-TUI 借鉴专项，供应链安全）
- [ ] Plan 15：Read-only tool parallelism（DeepSeek-TUI 借鉴专项，效率优化，后置）
- [x] Plan 16：LangGraph Runtime 边界收口（已由架构稳定化链路覆盖，不作为执行项）
- [x] Plan 17：LangGraph Intent 节点拆分（已由架构稳定化链路覆盖，不作为执行项）
- [x] Plan 18：LangGraph FilePatch 节点拆分（已由架构稳定化链路覆盖，不作为执行项）
- [ ] Plan 19：Graph residual governance and boundary regression（收缩版架构治理）
- [ ] Plan 20：Learner memory queue and debounce harness（DeerFlow harness 借鉴专项，后置）
- [ ] Plan 21：Deferred tool loading and tool_search harness（DeerFlow harness 借鉴专项，后置）

主线执行备注：Plan 11 已完成并推送。Plan 12 已拆为 12a / 12b / 12c，下一项从
Plan 12a 的本地 archive verifier dry-run 开始；12b 才接入 Plan 11 的受控 fetch。
Plan 16-18 的核心目标已在架构稳定化链路中落地，后续 graph 架构治理收束到 Plan 19
的残余边界与回归测试。

- [x] 旧 Plan C 链路：自动批量参数收集向导已完成，执行计划文件已从 `.work/plan/` 移除；历史决策留痕保留在 `.work/change/`。
- [ ] Plan C：Codex-style request lifecycle and runtime event model（索引；C1-C15 已落地并补齐记录，C16-C20 仍需完成/收口，按 `PlanC1.md` → `PlanC20.md` 逐项实施）
- [ ] Plan B1：Mode 分层、slash 切换、policy overlay、TUI 指示器与 audit schema（蓝队 v1；决策见 `change/2026-05-17-blueteam-mode.md` 与 `change/2026-05-17-blueteam-plan-trim.md`）
- [ ] Plan B2：Blueteam read-only triage runbook pack（蓝队 v1）
- [ ] Plan B3：Blueteam prompt overlay 与三段式 planner shaping（蓝队 v1）
- [ ] Plan B4：Blueteam respond runbooks (HITL-gated)（蓝队 v1）
- [ ] Plan B5：Blueteam audit forwarding 与分析师轨迹（蓝队 v1）
- [ ] Plan B6：蓝队 v1 端到端验收、文档与发版（吸收原 B10 适用部分）
- [ ] Plan B7：Universal stdin ingest PoC + ingest protocol + source recipes（独立节奏，**不进** v1 主线；决策见 `change/2026-05-17-blueteam-plan-trim.md` 与 `change/2026-05-17-ingest-stdin-direction.md`）
- ~~Plan B8：Source-aware enrichment~~ — **暂缓**（仅当 sample recipe 表达力不足且有真实流量证明时考虑；重启前必读 `plan/PlanB7.md` §后续 source 扩展的强制拆分规则）
- ~~Plan B9：OSQuery adapter~~ — **暂缓**（同上,重启拆 B9a–B9d 子项）
- ~~Plan B10：文档汇总~~ — **已并入 B6**（裁剪决策同上）
- [x] Plan D 链路：运行时 i18n 与 `language` 配置已完成，执行计划文件已从 `.work/plan/` 移除；历史决策留痕保留在 `.work/change/`。
- [x] Plan E 链路：架构稳定化与复杂度收口已完成，执行计划文件已从 `.work/plan/` 移除；历史决策留痕保留在 `.work/change/`。

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
