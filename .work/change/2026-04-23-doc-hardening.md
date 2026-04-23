# 文档一致性加固：八处内部冲突修正

- **日期**：2026-04-23
- **类型**：规则修订
- **影响范围**：`.gitignore`、`CLAUDE.md`、`AGENTS.md`、`rule/baseline.md`、`plan/Plan1.md`、`plan/Plan3.md`、`plan/Plan5.md`、`plan/Plan6.md`
- **决策者**：项目所有者

## 背景

第三方 code review 指出 `.work/` 文档体系虽然整体方向清晰，但存在 8 处会直接误导实施的内部冲突。本次收口一次性修正，避免 Plan 1 开工后反复在细节上返工。

## 修正清单

### ① `.gitignore` 吃掉了协作真源（Critical）

**原状**：`.gitignore:2-6` 忽略 `.claude/` / `.work/` / `CLAUDE.md` / `AGENTS.md` / `AGENT.md`，与 `.work/README.md:3` 声明的「共享工作区」直接矛盾。克隆仓库的人和 CI 都拿不到规则。

**修正**：从 `.gitignore` 移除 `.work/` / `CLAUDE.md` / `AGENTS.md` / `AGENT.md`，仅保留 `.claude/`（IDE / 本地 agent 缓存）。`.work/` 入库作为协作真源。

### ② CI 安全门禁恒成功（High）

**原状**：`plan/Plan6.md` 的
```
grep -r "shell=True" src/linuxagent/ && exit 1 || true
```
无论是否命中都退 0。

**修正**：改为 `! grep -rn 'shell=True' src/linuxagent/`；同时增加 `except:` 裸异常检查（呼应 R-QUAL-01）。

### ③ R-SEC-01 规则分歧（High）

**原状**：`AGENTS.md:58` / `CLAUDE.md:58` 写"禁止 `shell=True`"（绝对），`baseline.md:20` 给出"管道组合 + 硬编码常量"豁免。两者口径不一。

**修正**：**删除豁免**，改为零例外。理由：
- 豁免无法被 grep 门禁机械验证
- 「硬编码常量」很容易被变量拼接绕过
- Python 标准库 + `subprocess.run([...], stdin=...)` 已能覆盖所有管道场景

### ④ `--config <path>` 绕过权限校验（High）

**原状**：`plan/Plan1.md` §1.3 限定权限校验「仅对 `./config.yaml` 和 XDG 路径」，但 `--config /tmp/mine.yaml` 加载用户提交的含密钥文件时会绕过。

**修正**：权限 / 所有者校验覆盖**所有用户提供的路径**（含 `--config`、`LINUXAGENT_CONFIG`、`./config.yaml`、XDG）。**唯一豁免**是仓库内置模板 `configs/default.yaml` 与 `configs/example.yaml`（由 detect-secrets hook 保证不含真实密钥）。验收清单同步补充两条。

### ⑤ 依赖真源冲突（Medium）

**原状**：`.work/README.md:66` 称 `pyproject.toml` 是依赖真源；`plan/Plan6.md:138` 却以 `requirements.txt` 做最终清单；`baseline.md:165` R-DEP-01 要求 `pipreqs` 校验 `requirements.txt`。

**修正**：
- 运行时依赖唯一真源 = `pyproject.toml` 的 `[project.dependencies]`
- `requirements.txt` 在 Plan 1 开工时删除；若需 lockfile 走 `pip-compile` 生成 `requirements.lock`（入库，不手改）
- R-DEP-01 改为「pipreqs 与 pyproject 对齐」
- R-DEP-02 改为「开发/构建工具进 `[project.optional-dependencies.dev]`」
- Plan 6 §6.5 重写为 pyproject.toml 片段

### ⑥ Plan 3 文件命名不一致（Medium）

**原状**：`plan/Plan3.md:6` 交付物写 `graph/state.py`，§3.5 代码块注释写 `# graph/schema.py`。架构图使用 `state.py`。

**修正**：统一为 `graph/state.py`。

### ⑦ `langchain-community` 前禁后用（Medium）

**原状**：`plan/Plan3.md:22` 明确"不引入 langchain-community"，`plan/Plan5.md:135` 又加了该依赖。

**修正**：`InMemoryVectorStore` 在 `langchain-core >= 0.2.11` 已迁入 `langchain_core.vectorstores`，无需 community 包。Plan 5 的依赖表删除 `langchain-community`（同时删除 `sentence-transformers`，见 `2026-04-23-drop-pytorch-stack.md`）。

### ⑧ CLAUDE.md / AGENTS.md 同步条款自相矛盾（Medium）

**原状**：两文件头部都声称"内容同步"，但末节各有针对自己 agent 的专属段落。

**修正**：同步条款改为"**公共章节**必须同步；以 `## Claude 专属` 或 `## Agent 专属提示` 开头的章节允许分叉"。CLAUDE.md 相应章节已加上「Claude 专属：」前缀标识。

## 影响

- **受影响文档**：见上各小节
- **受影响代码**：无（尚未实现）

## 是否向后兼容

**是** —— 仅文档收口，不改变既定 v4 重写方向。同一主题若与更早的 `change/` 记录有冲突，按 `.work/README.md` 的裁决规则「日期更新者优先」，以本文件为准。
