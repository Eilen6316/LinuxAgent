# 迁移指南：v3 到 v4.0.0

LinuxAgent v4.0.0 是一次完整重写，不是旧原型的原地升级。

## 主要变化

| 领域 | v3 | v4.0.0 |
|---|---|---|
| 包布局 | 平铺原型代码 | `src/linuxagent/` src-layout 包 |
| 配置 | 临时文件和环境变量模式 | `config.yaml`，Pydantic v2 校验，要求 `chmod 600` |
| 命令安全 | 字符串包含判断 | 基于 token facts 的能力策略引擎 |
| LLM 输出 | 裸命令字符串 | 经过校验的 JSON `CommandPlan` |
| 编排 | 单个超大 Agent 类 | LangGraph 状态机 |
| SSH 信任 | 旧代码中存在不安全 host-key 行为 | 默认 `RejectPolicy` + 系统 `known_hosts` |
| 审计 | 可选或不完整 | 强制 hash-chained JSONL 审计日志 |
| 测试 | 缺少有效单测 | 单元、集成、harness、类型、lint、安全和构建门禁 |

## 必做迁移步骤

1. 使用 Python 3.11 或 3.12 创建新的虚拟环境。

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e .
```

2. 用 `config.yaml` 替换旧配置。

```bash
cp configs/example.yaml config.yaml
chmod 600 config.yaml
```

3. 把 API 凭据迁移到 `config.yaml`。

```yaml
api:
  provider: deepseek
  api_key: "replace-me"
```

不要用 `.env` 存密钥。v4 只允许环境变量指向配置路径，不承载密钥值。

4. 使用集群功能前先登记 SSH 主机。

```bash
ssh-keyscan -H your-host.example.com >> ~/.ssh/known_hosts
```

v4 默认拒绝未知 host key。

5. 本地验证。

```bash
linuxagent check
linuxagent
```

## 操作员会感知到的行为变化

- LLM 首次生成的命令需要确认。
- 破坏性命令每次都要确认，永不进入白名单。
- 非交互调用遇到命令确认会自动拒绝。
- 对两台及以上主机的集群操作需要显式批量确认。
- SSH 集群模式可能阻断命令串联、重定向、命令替换或变量展开。
- 进入 LLM 分析路径的命令输出会先经过 guard 和脱敏。

## 旧自定义能力的替代方式

| 旧自定义 | v4 替代方式 |
|---|---|
| 直接改 prompt | 修改 `prompts/` |
| 直接改命令 allow/block 逻辑 | 参考 `configs/policy.default.yaml` 并配置 `policy.path` |
| 自定义脚本工作流 | 在 `runbooks/` 添加 YAML runbook，并补 harness 场景 |
| 本地历史逻辑 | 使用内置 audit 和 telemetry 文件 |

## 回滚建议

v3 和 v4 应保持独立部署。不要在两个版本之间共享配置文件、历史文件或审计文件。
如果仍需保留 v3 处理遗留流程，请使用单独 checkout，并避免与 v4 包混合 import。
