# AGENTS.md

> 给 Codex、Cursor、Aider 等 AI coding agent 的入口文档。
> 与 `CLAUDE.md` 的**公共章节**必须保持同步；以 `## Claude 专属` 或 `## Agent 专属提示` 开头的章节允许按 agent 分叉，修改时无需对齐（但需保留明确标题）。公共章节任一改动须两边一起改，或在 `.work/change/` 留痕说明仅更新单边的原因。

---

## 这是什么项目

LinuxAgent 是一个基于 LLM 的 Linux 运维助手 CLI。
**当前状态：v3 代码库处于冻结 / 将被替换状态，v4 完全重写方案已就绪。**

v3 的主要问题（来自 2026-04-23 的 code review）：
- `src/agent.py` 4710 行 / 86 方法的 God Object
- 多处 `shell=True` + 未校验 LLM 输出的命令注入风险
- 危险命令过滤用字符串 `in`，正则完全失效
- SSH `AutoAddPolicy`，无主机密钥验证
- 零单元测试

v4 改用 **LangGraph + LangChain + Pydantic v2 + YAML 场景 Harness**。

---

## 强制阅读顺序

**在做任何实现或修改之前，按顺序读以下文档：**

1. `.work/README.md` —— 协作目录总览 + 当前进度
2. `.work/rule/baseline.md` —— 项目级编码约定（R-SEC / R-ARCH / R-QUAL / R-TEST / R-DEP）
3. `.work/rule/python.md` —— Python 特定规则
4. `.work/design/architecture.md` —— 架构决策与技术栈
5. `.work/plan/PlanN.md` —— 当前要实施的轮次（N = 1…6）
6. `.work/change/` —— 所有历史决策变更，尤其是最近的

---

## 单一真源（Source of Truth）

| 类型 | 权威位置 | 不要在哪里重复 |
|---|---|---|
| 架构决策 | `.work/design/architecture.md` | 不要写进 plan 或代码注释 |
| 编码约定 | `.work/rule/*.md` | 不要写进 plan、prompt、或 AGENTS.md |
| 实施步骤 | `.work/plan/PlanN.md` | 不要写进架构文档 |
| Prompt 模板 | `prompts/` | 不要硬编码进 Python 文件，也不要写进 `.work/prompt/` |
| 偏离记录 | `.work/change/` | 不要修改历史条目，只追加 |

**偏离任何权威文档之前，必须先在 `.work/change/` 写一条记录**，格式见 `.work/change/TEMPLATE.md`。
**同一主题若多条 `change/` 记录互相冲突，以日期更新者为准。**

---

## 不可协商的红线

以下规则违反将被拒绝合并（参见 `.work/rule/baseline.md` 完整版）：

| ID | 规则 |
|---|---|
| R-SEC-01 | 禁止 `shell=True`；subprocess 必须用列表参数 |
| R-SEC-02 | 命令安全检测必须用 `shlex.split` 的 token 级分析，禁止 `pattern in command` |
| R-SEC-03 | SSH 禁止 `AutoAddPolicy`，必须 `RejectPolicy` + `load_system_host_keys()` |
| R-SEC-04 | 密钥只走 `config.yaml`（chmod 600），禁止 `.env` / 环境变量承载实际值，使用 `SecretStr` |
| R-HITL-01 | LLM 生成的命令首次必须 CONFIRM；会话白名单仅进程内有效 |
| R-HITL-03 | 破坏性命令（`rm -rf` / `mkfs` / `dd` / `systemctl stop` 等）永不进白名单 |
| R-HITL-05 | confirm 节点必须用 `langgraph.types.interrupt()`，图节点内禁 `input()` |
| R-HITL-06 | 所有人工决策追加到 `~/.linuxagent/audit.log`（JSONL，`0o600`，不轮转） |
| R-ARCH-01 | `src/linuxagent/app/agent.py` 行数 ≤ 300 |
| R-ARCH-04 | Config 必须 Pydantic fail-fast，禁止 `getattr(config, 'k', default)` 绕过验证 |
| R-QUAL-01 | 裸 `except` 禁止 |
| R-TEST-02 | 安全相关测试不得 mock 核心检查逻辑 |

---

## 工作节奏

1. **接到任务** → 查 `.work/README.md` 的「当前状态」清单，找到下一个未完成的 Plan
2. **读对应 Plan** → 不要跨 Plan 实施；每个 Plan 的「前置条件」必须已满足
3. **如果遇到决策分歧** → 先查 `.work/design/architecture.md` 和 `.work/change/`；找不到再问人
4. **如果需要偏离计划** → 先写 `.work/change/YYYY-MM-DD-slug.md`，再改代码
5. **完成一轮** → 在对应 `PlanN.md` 末尾追加「完成记录」（日期 + commit hash + 偏差清单），并更新 `.work/README.md` 的复选框
6. **提交** → commit message 引用 Plan 编号，例如 `plan1: add AppConfig pydantic models`

---

## 禁止事项

- ❌ 不要修改 `src/` 旧代码去"顺手修复" v3 的问题 —— v3 将整体替换
- ❌ 不要跳过 Plan 顺序（Plan 3 依赖 Plan 1，Plan 4 依赖 Plan 2+3）
- ❌ 不要在根目录或 `src/` 创建新业务文件 —— 新代码一律放 `src/linuxagent/` 新包
- ❌ 不要在 `.work/plan/` 里重复 `rule/` 或 `architecture.md` 的内容
- ❌ 不要把临时分析、TODO、或个人笔记放进 `.work/` —— 这里只收权威文档

---

## Agent 专属提示

### 对 Codex / OpenAI Agent

- 本仓库使用 LangChain Core 而不是 OpenAI SDK 原生调用。需要接入新模型时，使用 `langchain-openai` 的 `ChatOpenAI`，不要直接 `import openai`
- 测试场景请用 `langchain_core.language_models.fake.FakeChatModel` 替代真实 API

### 对 Cursor / Aider

- `.work/` 下的所有 Markdown 文件都应在工作上下文里（Cursor: add to context；Aider: `/read` 添加）
- 修改前务必确认当前 Plan 的「前置条件」

---

## 目录布局（v4，src-layout）

完整结构见 `.work/design/architecture.md` §目录结构。要点：

```
src/linuxagent/     ← 唯一发布包，所有新代码只进这里
tests/              ← unit / integration / harness，镜像 src 结构
prompts/            ← Prompt 模板（非 Python）
configs/            ← 配置样例
legacy/             ← v3 冷藏区，禁止修改
pyproject.toml      ← PEP 517/621 单一真源
Makefile            ← 常用命令
```

## 快速命令参考（v4 实施阶段）

```bash
# 每一轮开工前
cat .work/plan/PlanN.md

# 检查红线是否被违反
grep -rn "shell=True" src/linuxagent/
grep -rn "AutoAddPolicy" src/linuxagent/
grep -rn "except:" src/linuxagent/

# 运行测试和类型检查
make test          # pytest tests/unit/ --cov=linuxagent --cov-fail-under=80
make type          # mypy src/linuxagent/
make lint          # ruff check src/linuxagent/
make harness       # python -m tests.harness.runner
```
