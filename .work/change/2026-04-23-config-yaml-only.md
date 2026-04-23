# 统一走 config.yaml，不使用 .env

- **日期**：2026-04-23
- **类型**：设计变更
- **影响范围**：`rule/baseline.md` R-SEC-04、`rule/python.md`、`plan/Plan1.md`、`design/architecture.md` 目录树、`CLAUDE.md` / `AGENTS.md`
- **决策者**：项目所有者

## 背景

初版 Plan 1 和 baseline.md 规定敏感值（API Key）从环境变量读取，通过 `.env.example` 维护模板。这会造成：
- 配置被拆到两个位置（`config.yaml` 放非敏感项，`.env` 放密钥），新人容易漏配
- CLI 工具用户习惯一份 YAML 统管所有设置
- 原 v3 已经在 `config.yaml` 的 `api.api_key` 里管理密钥，用户已形成使用习惯

## 新决策

**一份 `config.yaml` 包办所有配置（含密钥）**，彻底去掉 `.env` 相关设计。

### 1. 配置文件布局

| 路径 | 内容 | 是否入库 |
|---|---|---|
| `configs/default.yaml` | 默认值 + 占位密钥（`api_key: ""`） | ✅ 入库 |
| `configs/example.yaml` | 完整注释版样例，供 copy | ✅ 入库 |
| `./config.yaml`（仓库根） | 用户本地实际配置 | ❌ **gitignore** |
| `~/.config/linuxagent/config.yaml` | 用户全局配置（可选） | — |

### 2. 加载优先级（`config/loader.py`）

```
1. CLI 参数 --config <path>
2. 环境变量 LINUXAGENT_CONFIG（仅指向路径，不承载值）
3. ./config.yaml（当前目录）
4. ~/.config/linuxagent/config.yaml（XDG）
5. configs/default.yaml（仓库内置默认）
```

优先级越高越优先。高优先级覆盖低优先级（同 key）。**不支持 `.env`、不支持 `${VAR}` 环境变量插值**。

### 3. 安全加固

由于 `config.yaml` 将承载密钥，必须强化：

- **文件权限**：加载时检查，非 `0600` 则拒绝启动并提示 `chmod 600 config.yaml`
- **所有者检查**：文件所有者必须是当前用户
- **Pydantic `SecretStr`**：密钥字段用 `SecretStr` 防止 `repr` / 日志泄露
- **gitignore**：`./config.yaml` 默认忽略；`configs/default.yaml` 和 `configs/example.yaml` 只允许占位值入库
- **预提交检查**：添加 `detect-secrets` 或自定义 hook，阻止真实密钥提交

### 4. 环境变量的角色（受限）

环境变量**仅用于指定路径或切换 profile**，不承载任何配置值：

| 变量 | 作用 |
|---|---|
| `LINUXAGENT_CONFIG` | 指定 config.yaml 路径 |
| `LINUXAGENT_PROFILE` | 选择 profile（如 `dev`、`prod`），映射到 `configs/<profile>.yaml` |
| `LANGCHAIN_TRACING_V2`、`LANGCHAIN_API_KEY` | LangSmith 追踪用（第三方框架原生要求，例外） |

## 影响

- **受影响文档**：
  - `rule/baseline.md` R-SEC-04 重写：密钥在 yaml 中管理，通过文件权限而非环境变量保护
  - `rule/python.md` Pydantic 示例改为从 yaml 字段加载
  - `plan/Plan1.md` §1.1.4 删除 `.env.example`；§1.2 修改 Config 加载策略；验收标准加入文件权限检查
  - `design/architecture.md` 目录树删除 `.env.example`
  - `CLAUDE.md` / `AGENTS.md` 的命令示例无变化（本来就用 `configs/default.yaml`）
  - `.gitignore` 保留 `.env` 忽略（防止意外创建），但不再作为正常流程

## 是否向后兼容

**向后兼容 v3 用户习惯**（v3 就是用 yaml 管理密钥），**不兼容初版 Plan 1 的 `.env` 方案**（该方案尚未实施，仅文档层面）。
