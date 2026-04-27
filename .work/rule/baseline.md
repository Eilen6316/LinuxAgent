# baseline.md · 项目级编码约定

> **状态**：有效  
> **适用范围**：所有在本仓库提交的 Python 代码  
> 规则可增不可删；删除或放宽需在 `change/` 中记录原因并获得评审。

---

## R-SEC：安全规则（不可妥协）

### R-SEC-01 禁止 `shell=True`
所有 `subprocess` 调用**必须**使用列表参数：
```python
# ✅ 正确
subprocess.run(["ls", "-la", path], capture_output=True, timeout=30)

# ❌ 禁止
subprocess.run(f"ls -la {path}", shell=True)
```
**零例外**。管道组合必须用 `subprocess.run([...], stdin=..., stdout=PIPE)` 串联两个进程，或用 Python 标准库（`glob`、`pathlib`、`gzip` 等）替代。历史上的「硬编码常量」豁免无法被 grep 门禁机械验证，已取消。

### R-SEC-02 命令安全检测必须使用 token 级分析
```python
import shlex, re

def is_dangerous(cmd: str) -> bool:
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        return True  # 解析失败视为危险
    # 检测命令名 + 参数组合
    ...
```
**禁止**：`if pattern in command`（字符串包含）用于安全判断。

### R-SEC-03 SSH 必须验证主机密钥
```python
# ✅ 正确
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.load_system_host_keys()

# ❌ 禁止
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
```

### R-SEC-04 敏感配置只走 config.yaml + 强权限
密钥（API Key、SSH 密码等）**只能**写在 `config.yaml` 中，禁止：
- 写入日志（含 DEBUG 级别）
- 出现在 `__repr__` / `__str__`
- 提交到 git（`./config.yaml` 默认 gitignore）
- 通过 `.env` / 命令行参数 / 环境变量承载实际值

加载时必须同时满足：
1. 文件权限 `0o600`，非 `0o600` 则 `ConfigPermissionError` 拒绝启动
2. 文件所有者为当前用户（`stat().st_uid == os.getuid()`）
3. Pydantic 模型用 `SecretStr`，取值通过 `.get_secret_value()` 显式调用

```python
# ✅ 正确
class APIConfig(BaseModel):
    api_key: SecretStr
    ...

def load_config(path: Path) -> AppConfig:
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise ConfigPermissionError(f"{path} must be chmod 600, got {oct(mode)}")
    ...
```

环境变量**只用于指定配置路径**（`LINUXAGENT_CONFIG`、`LINUXAGENT_PROFILE`），不承载值。例外：LangSmith 追踪相关变量（第三方框架原生要求）。

### R-SEC-05 历史文件权限
写入 `~/.linuxagent_*.json` 时必须 `chmod 0o600`：
```python
path.touch(mode=0o600, exist_ok=True)
```

---

## R-HITL：Human-in-the-Loop 规则（不可妥协）

运维 Agent 的 HITL 是一等原则。下述规则定义**何时必须问人**、**如何问**、**可否降级**。违反任一条视为与 R-SEC 同级的红线。

### R-HITL-01 LLM 输出默认不可信
任何 LLM 生成的命令字符串首次出现时，**必须**经过一次人工 CONFIRM，即使 token 级安全检测判定为 SAFE。经用户批准后可加入**会话级白名单**（归一化命令 + 参数模式），仅在当前进程生命周期内降级为 SAFE；进程退出即失效。**禁止**跨会话持久化白名单。

### R-HITL-02 批量操作强制确认，不可降级
SSH 集群操作的目标主机数 ≥ `cluster.batch_confirm_threshold`（默认 `2`）时，**必须**以下述两种模式之一获得确认：

- **全部同意一次**：预览所有主机 + 命令，用户一次批准
- **逐台确认**：逐台弹出 confirm，用户可在任意一台中止

本规则**不受** `--yes` / 会话白名单影响。

### R-HITL-03 破坏性命令永不进白名单
命中 policy 配置中 `never_whitelist: true` 规则的命令，**每次**执行都必须 CONFIRM，即使已在会话白名单中。破坏性模式清单定义在 `configs/policy.default.yaml` 或用户配置的 policy YAML 中，Python 代码只负责加载、校验和执行这些规则；修改默认策略需走 `change/`。

### R-HITL-04 `--yes` 仅对会话级生效
`--yes` / `--no-confirm` / `--batch` 仅对**无直接副作用**的对话级确认生效（如"是否加载历史"、"是否进入多轮对话"）。对以下**一律无效**：

- 命令级 CONFIRM / BLOCK
- R-HITL-02 批量操作
- R-HITL-03 破坏性命令

**非交互环境（无 TTY）** 中遇到 CONFIRM 请求：**默认拒绝**（记录为 `decision: non_tty_auto_deny`），禁止静默通过。

### R-HITL-05 使用 LangGraph `interrupt()` 原语
confirm 节点**必须**通过 `langgraph.types.interrupt()` 实现，中断点由 `MemorySaver` 持久化。**禁止**在图节点内同步调用 `input()` / `prompt_async()` / `click.confirm()`。理由：
- 中断点可序列化，支持 Ctrl-C 恢复（`Command(resume=...)`）
- 非 CLI 前端（Web / API / LangSmith Studio）可直接对接同一流程，无需双实现

### R-HITL-06 所有人工决策留痕
每次 HITL 事件（请求 + 决策 + 执行结果）追加到审计日志 `~/.linuxagent/audit.log`，JSONL 格式，文件权限 `0o600`，**不轮转不截断**。字段至少：

```json
{
  "ts": "2026-04-23T14:30:00+08:00",
  "session_id": "...",
  "checkpoint_id": "...",
  "command": "rm -rf /tmp/foo",
  "command_source": "llm|user|whitelist",
  "safety_level": "CONFIRM",
  "matched_rule": "DESTRUCTIVE_RM",
  "batch_hosts": ["host-a", "host-b"],
  "decision": "yes|no|non_tty_auto_deny|timeout",
  "latency_ms": 4280,
  "exit_code": 0
}
```

敏感值（已知密钥字段、Authorization header 等）写入前脱敏为 `***redacted***`；命令原文本身**不脱敏**（审计需要可追溯）。磁盘容量管理由用户负责，`logrotate` 归档不得覆盖 / 删除当前文件。

---

## R-ARCH：架构规则

### R-ARCH-01 Agent 类行数上限 300 行
`src/linuxagent/app/agent.py` 只做协调（组合服务调用），**禁止**在此实现业务逻辑。  
业务逻辑放对应的 `src/linuxagent/services/` 模块。

### R-ARCH-02 服务间依赖必须通过接口
服务类只依赖 `src/linuxagent/interfaces/` 中的抽象类，不得直接 `import` 具体实现。

### R-ARCH-03 统一使用相对导入
同一包内一律使用相对导入：
```python
# ✅ 正确
from .config import AppConfig
from ..interfaces import LLMProvider

# ❌ 禁止
from src.config import AppConfig
```

### R-ARCH-04 Config 必须 fail-fast
启动时用 Pydantic `model_validate` 解析全部配置节；任何字段类型错误立即抛出，不得使用 `getattr(config, 'key', default)` 绕过验证。

### R-ARCH-05 禁止全局可变状态
禁止模块级可变变量（除 `logger`）。所有状态通过实例属性或显式传参管理。

### R-ARCH-06 禁止在 Python 中硬编码业务判断规则
意图分流、运维语义判断、命令生成策略、故障恢复策略等可变业务规则不得用 Python 关键词表、字符串包含、分支枚举等方式写死在代码中。此类规则必须放在单一真源：

- Prompt 模板：`prompts/`
- 策略配置：`configs/policy.default.yaml` 或用户配置的 policy YAML
- Runbook：`runbooks/`
- Pydantic 模型/枚举：仅用于承载结构化协议，不承载业务规则

Python 代码只负责解析结构化输出、执行状态机、调用 policy/runbook/prompt，以及 fail-fast 校验。若确需新增硬编码安全不变量，必须先在 `.work/change/` 记录原因，并且仅限 R-SEC / R-HITL 红线级约束。

测试中也不得把具体运维方法（如某产品改密 SQL、安装流程）作为固定答案写死；只能验证协议、状态流转、安全拦截、脱敏和记忆持久化等行为。具体方法由模型在运行时生成，执行成功后由 learner memory 记录脱敏后的成功命令模式。

---

## R-QUAL：代码质量规则

### R-QUAL-01 裸 `except` 禁止
```python
# ✅ 正确
except (ValueError, KeyError) as e:
    logger.warning("...", exc_info=e)

# ❌ 禁止
except:
    pass
except Exception:
    pass  # 不记录的吞掉异常
```

### R-QUAL-02 函数行数上限 50 行
超出时必须拆分。生成器、复杂流式处理可申请豁免，需在 `change/` 记录。

### R-QUAL-03 禁止方法内 import
`import` 语句只写在文件顶部。

### R-QUAL-04 魔法数字必须命名
```python
# ✅ 正确
MAX_CHAT_HISTORY = 20
STREAM_CHUNK_TIMEOUT = 30.0

# ❌ 禁止
if len(history) > 20: ...
```

### R-QUAL-05 注释只写 WHY，不写 WHAT
代码本身表达 WHAT；注释说明不明显的约束、绕过的 bug、或反直觉的实现原因。

---

## R-TEST：测试规则

### R-TEST-01 每个公共函数/方法至少一个单元测试
新增代码的测试覆盖率不得低于 **80%**（`pytest-cov` 检查）。

### R-TEST-02 不得 mock 文件系统和子进程用于安全测试
安全相关测试（命令过滤、SSH 策略）必须使用真实逻辑路径，不得用 mock 替代关键安全检查。

### R-TEST-03 测试文件与源文件一一对应
`src/linuxagent/services/command_service.py` → `tests/unit/services/test_command_service.py`

### R-TEST-04 集成测试隔离
集成测试放 `tests/integration/`，默认不在 CI 主流程运行（需 `--integration` 标志）。

---

## R-DEP：依赖规则

### R-DEP-01 运行时依赖必须实际使用
新增依赖前确认无法用标准库实现。运行时依赖的**唯一真源**是 `pyproject.toml` 的 `[project.dependencies]`；每次 PR 需 `pipreqs src/linuxagent/` 与 pyproject 对齐，pyproject 列出但未被 import 的包视为幽灵依赖，需在 `change/` 说明或删除。**不使用 `requirements.txt` 作为真源**（如存在应由 `pip-compile` 生成为 lockfile）。

### R-DEP-02 构建与开发工具不进运行时依赖
`pyinstaller`、`build`、`mypy`、`ruff`、`pytest` 等放 `[project.optional-dependencies.dev]` 或专门的 extras group，不进 `[project.dependencies]`。

### R-DEP-03 固定主版本号
```
pydantic>=2.0,<3.0
paramiko>=3.0,<4.0
```
禁止裸版本（`pydantic`）或过宽范围（`pydantic>=1.0`）。
