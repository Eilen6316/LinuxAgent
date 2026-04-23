# 统一 Prompt / 配置 / 路径文档口径

- **日期**：2026-04-23
- **类型**：规则修订
- **影响范围**：`AGENTS.md`、`CLAUDE.md`、`.work/README.md`、`design/architecture.md`、`plan/Plan1.md`、`plan/Plan3.md`、`rule/baseline.md`
- **决策者**：项目所有者

## 背景

在补齐 `AGENTS.md` 和 `.work/` 后，文档间仍存在三类冲突：

- Prompt 真源同时写成了 `.work/prompt/` 与仓库根 `prompts/`
- `config.yaml-only` 已禁止 `.env`，但少量文档仍残留旧表述
- 路径规范已切到 `src/linuxagent/`，但个别规则文本仍沿用旧的 `src/...` 写法

这些冲突不会改变架构方向，但会直接误导后续 agent 的实施路径。

## 新决策

1. **运行时 Prompt 模板唯一真源固定为仓库根 `prompts/`**
2. **`.work/prompt/` 仅作兼容占位，不参与运行时加载**
3. **继续沿用 `config.yaml-only` 方案，不再在当前有效文档中保留 `.env` 流程**
4. **当前有效实现路径统一使用 `src/linuxagent/...`**
5. **同一主题若多个 `change/` 文件冲突，以日期更新者为准**

## 影响

- **受影响文档**：
  - `AGENTS.md` / `CLAUDE.md`：更新 Source of Truth、冲突裁决规则、路径表述
  - `.work/README.md`：重写 `prompt/` 目录职责，补充最新变更优先规则
  - `design/architecture.md`：修正 CLI 层路径与 D-2 标题措辞
  - `plan/Plan1.md`：放宽骨架演进表述
  - `plan/Plan3.md`：统一 Prompt 加载目录为 `prompts/`
  - `rule/baseline.md`：统一路径示例为 `src/linuxagent/...`

- **受影响代码**：无，仅文档收口

## 是否向后兼容

**是** —— 仅统一当前有效文档口径，不改变既定的 v4 重写方向。
