# Plan 8 · 能力驱动的策略引擎

**目标**：把硬编码安全分类器升级为 capability-based policy engine，同时保持 `SAFE / CONFIRM / BLOCK` 兼容接口。

**前置条件**：Plan7 完成。

**交付物**：`src/linuxagent/policy/` + `configs/policy.default.yaml` + policy golden tests。

---

## Scope

- 新增 `PolicyDecision`：`level`、`risk_score`、`capabilities`、`matched_rules`、`approval`
- `executors/safety.py` 保留 facade，底层委托 policy engine
- policy 默认规则覆盖 filesystem、service、package、container、kubernetes、sudo、network/firewall
- 配置文件可覆盖或追加规则
- 每条规则必须 token/path/capability 级匹配，禁止回退到裸字符串包含判断

## 验收标准

- [x] 原有 safety 单测全部通过
- [x] 新增不少于 100 条危险命令 golden cases
- [x] 每条命令输出 `level`、`risk_score`、`capabilities`、`matched_rules`
- [x] policy 配置 fail-fast 验证
- [x] README / docs 给出 policy 示例

<!-- 完成记录（完成后追加） -->

## 完成记录

- **日期**：2026-04-25
- **实现 commit**：`20a1b41`
- **偏差清单**：
  - 默认运行时使用 `builtin_rules.py`，`configs/policy.default.yaml` 作为可读模板和后续覆盖入口；本轮未把 policy path 接入 `AppConfig`，避免扩大配置迁移范围。
  - `executors/safety.py` 保持兼容 facade，返回 `SafetyResult`；丰富的 `PolicyDecision` 当前通过 `policy.PolicyEngine` 暴露。
