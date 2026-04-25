# Plan8 策略引擎实施范围

- **日期**：2026-04-25
- **类型**：设计变更 + 实施记录
- **影响范围**：`.work/plan/Plan8.md`、`src/linuxagent/policy/`、`src/linuxagent/executors/safety.py`、`configs/policy.default.yaml`
- **决策者**：项目所有者 + Codex

## 背景

Plan8 要求把硬编码的 `SAFE / CONFIRM / BLOCK` 分类器升级为 capability-based policy engine，但当前代码已有稳定的 `executors.safety.is_safe()` API，被 executor、HITL、whitelist、测试广泛依赖。

## 新决策

1. 新增内部 `src/linuxagent/policy/`，提供 `PolicyDecision`、`PolicyRule`、`PolicyConfig` 和 `PolicyEngine`。
2. `executors/safety.py` 保留 facade API，底层委托 `DEFAULT_POLICY_ENGINE.evaluate()`，并继续返回 `SafetyResult`，避免破坏现有 graph/executor 调用。
3. 默认规则同时保存在代码 `builtin_rules.py` 和可读模板 `configs/policy.default.yaml`；运行时默认使用代码内置规则，避免每次安全判断依赖文件 I/O。
4. `config_rules.py` 提供 fail-fast YAML 加载入口，供后续 Plan 或用户覆盖策略使用；本轮不把 policy path 加入 `AppConfig`，避免扩大配置迁移范围。
5. 旧测试期望的 `matched_rule` 保持兼容，如 `DESTRUCTIVE`、`SENSITIVE_PATH`、`LLM_FIRST_RUN`。

## 影响

- **受影响文档**：
  - `.work/plan/Plan8.md`
- **受影响代码**：
  - `src/linuxagent/policy/`
  - `src/linuxagent/executors/safety.py`
  - `configs/policy.default.yaml`
  - `pyproject.toml`

## 是否向后兼容

是。外部调用 `is_safe()`、`is_destructive()`、`is_interactive()` 的行为保持兼容；新增的 `PolicyDecision` 只扩展能力，不替换现有接口。
