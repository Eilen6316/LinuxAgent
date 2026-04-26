# Commit message 不再使用 plan 字样

- **日期**：2026-04-26
- **类型**：协作规范变更
- **影响范围**：后续 git commit message
- **决策者**：项目所有者

## 背景

历史提交使用了 `planN: ...` 格式。项目所有者要求从下一次提交开始，包括以后所有提交，commit 记录中不要再带有 `plan` 字样。

## 新决策

1. 后续 commit message 不再使用 `plan`、`Plan`、`planN` 等字样。
2. commit message 改用能力/范围描述，例如：
   - `security: harden ssh remote command execution`
   - `docs: record ssh hardening completion`
3. `.work/plan/PlanN.md` 作为既有协作文档路径和轮次索引暂时保留，不纳入本次改名范围。

## 是否向后兼容

是。只影响未来提交信息，不改写历史 commit。
