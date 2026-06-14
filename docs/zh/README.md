<div align="center">
  <h1>LinuxAgent</h1>
  <img src="../../logo.jpg" alt="LinuxAgent Logo" width="320" />

  <p>
    <a href="https://github.com/Eilen6316/LinuxAgent.git"><img src="https://img.shields.io/badge/GitHub-项目仓库-black?style=flat-square&logo=github" alt="GitHub"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/Eilen6316/LinuxAgent/ci.yml?branch=master&style=flat-square&label=CI" alt="CI"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.1.0"><img src="https://img.shields.io/github/v/release/Eilen6316/LinuxAgent?style=flat-square" alt="Release"></a>
    <a href="https://github.com/Eilen6316/LinuxAgent/releases/tag/v4.1.0"><img src="https://img.shields.io/badge/package-GitHub%20Release-blue?style=flat-square" alt="GitHub Release package"></a>
    <a href="../../SECURITY.md"><img src="https://img.shields.io/badge/security-policy-green?style=flat-square" alt="Security Policy"></a>
    <a href="https://gitcode.com/qq_69174109/LinuxAgent.git"><img src="https://img.shields.io/badge/GitCode-项目仓库-blue?style=flat-square&logo=git" alt="GitCode"></a>
    <a href="https://gitee.com/xinsai6316/LinuxAgent.git"><img src="https://img.shields.io/badge/Gitee-项目仓库-red?style=flat-square&logo=gitee" alt="Gitee"></a>
    <a href="http://qm.qq.com/cgi-bin/qm/qr?_wv=1027&k=o2ByKsl_gBN-fODJxH4Ps4Xboa_hCSI3&authKey=nVfsLJBin1CnZBd9pPNkxFk%2FGFqCe1FLsRMQmmxv%2FQnM78bC%2FjcWyMSeQcJDZC1U&noverify=0&group_code=281392454"><img src="https://img.shields.io/badge/QQ群-281392454-brightgreen?style=flat-square&logo=tencent-qq" alt="QQ Group"></a>
    <a href="https://blog.csdn.net/qq_69174109/article/details/146365413"><img src="https://img.shields.io/badge/CSDN-项目介绍-blue?style=flat-square&logo=csdn" alt="CSDN"></a>
  </p>

  <p><em>LinuxAgent v4.1.0：LLM 辅助的 Linux 运维 CLI，命令执行前必须经过确定性策略检查和人机确认。</em></p>

  <p>
    <a href="../../README.md">Project homepage</a> ·
    <a href="../en/README.md">Full English</a>
  </p>
</div>

---

## 项目介绍

LinuxAgent 允许 LLM 提议 Linux 运维操作，但不会把模型当成可自治执行的
shell。命令会先被解析并交给确定性策略分类；需要审批时展示给人工确认；
执行时不使用 `shell=True`；输出在进入模型分析前会脱敏；所有关键决策写入本地审计日志。

适合这些场景：

- 日常巡检：文件、日志、端口、资源占用、服务状态
- 交互式排障：模型提出下一条命令，操作员决定是否执行
- 对已配置主机做 SSH 批量操作，并在扩散前显式批量确认
- 需要本地 JSONL 审计轨迹的环境

更深入的安全架构、威胁模型和 v3 迁移说明，请阅读
[操作员安全模型](operator-safety.md)、[威胁模型](threat-model.md) 和
[v3 到 v4 迁移](migration-v3-to-v4.md)。

## 安装

### 自动安装

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh
```

bootstrap 会创建 `.venv`、准备 `~/.config/linuxagent/config.yaml`、
创建 `~/.local/bin/linuxagent` 启动器，并把 `LINUXAGENT_CONFIG` 写入 shell
profile。之后请打开新 shell，或 source 对应 profile，再从其他目录启动。

### 手动安装

```bash
python3.11 -m venv .venv   # 也支持 python3.12
source .venv/bin/activate
pip install -e ".[dev]"
mkdir -p ~/.config/linuxagent ~/.local/bin
cp configs/example.yaml ~/.config/linuxagent/config.yaml
chmod 600 ~/.config/linuxagent/config.yaml
ln -sf "$PWD/.venv/bin/linuxagent" ~/.local/bin/linuxagent
```

可选扩展：

```bash
pip install -e ".[anthropic]"     # Claude 支持
pip install -e ".[pyinstaller]"   # 单二进制打包
```

运行时需要 Linux 和 Python 3.11 或 3.12。macOS 可用于开发，Windows 暂不支持。
SSH 集群模式要求目标主机已经登记在 `~/.ssh/known_hosts`。

## 最小配置

编辑 `~/.config/linuxagent/config.yaml`，并确保文件权限是私有的：

```yaml
# ~/.config/linuxagent/config.yaml
api:
  api_key: "sk-replace-me"
```

默认 provider 是 DeepSeek。OpenAI 兼容中转站可这样配置：

```yaml
api:
  provider: openai_compatible
  base_url: https://relay.example.com/v1
  model: gpt-4o-mini
  api_key: "sk-replace-me"
  token_parameter: max_tokens
```

本地 OpenAI 兼容服务，例如 Ollama：

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

首次使用前先验证：

```bash
chmod 600 ~/.config/linuxagent/config.yaml
linuxagent check
```

常用 provider 包括 `deepseek`、`openai`、`openai_compatible`、`local`、
`ollama`、`vllm`、`lmstudio`、`qwen`、`kimi`、`glm`、`minimax`、
`gemini`、`hunyuan`、`anthropic`、`anthropic_compatible` 和
`xiaomi_mimo`。完整字段请看
[Provider 兼容矩阵](provider-matrix.md) 和
[`configs/example.yaml`](../../configs/example.yaml)。

## 首次使用

启动对话界面：

```bash
linuxagent
```

先试一个只读请求：

```text
check the Linux version
```

对话中的第一条 LLM 生成命令通常会要求确认：

```text
linuxagent > 找一下监听 8080 端口的服务

LLM proposes: ss -tlnp sport = :8080
Safety: CONFIRM
Rule: LLM_FIRST_RUN
Allow this operation?
1. Yes
2. Yes, don't ask again in this conversation/resume
3. No
```

`Yes, don't ask again` 只对当前 conversation thread 及同一 thread 的
`/resume` 生效，不是全局白名单。操作员自己输入的直接命令可以用 `!` 前缀，
例如 `!uname -a`。

常用 slash 命令：

| 命令 | 用途 |
|---|---|
| `/resume` | 恢复本地保存的会话；未完成确认会重新打开 |
| `/new` 或 `/clear` | 在当前 CLI 中开启空上下文对话 |
| `/tools` | 查看可用 slash/tool 入口 |
| `/job` | 查看已批准的后台任务 |
| `/help` | 显示 CLI 帮助 |
| `/exit` 或 `/quit` | 退出 |

## 必须记住的安全规则

- 模型不可信：LLM 生成的命令必须先通过确定性策略判断。
- LLM 首次生成的命令需要人工确认，即使命令看起来安全。
- `rm -rf`、`mkfs`、`dd`、`systemctl stop` 等破坏性命令永不进入对话白名单。
- `BLOCK` 命令在确认节点之前就会停止；典型例子包括删除根文件系统、访问
  `/etc/shadow` 等敏感路径、隐藏危险行为的命令替换、fork bomb 和非法 shell 输入。
- 非交互运行不能静默批准 `CONFIRM`，会 fail closed。
- SSH 使用 known-host 校验并拒绝未知主机；远端命令在执行前被限制为简单 argv 风格。
- 审计日志不能关闭，并以私有权限写入。

安全策略入口是 [SECURITY.md](../../SECURITY.md)、
[`configs/policy.default.yaml`](../../configs/policy.default.yaml) 和
`src/linuxagent/policy/`。

## 常用场景

### 安全巡检

```text
linuxagent > 看一下当前目录的文件
LLM proposes: ls -la
Safety: CONFIRM, Rule: LLM_FIRST_RUN
```

如果选择对话级批准，相同 argv 形态可以在当前对话或其 `/resume` thread 中再次执行。
新对话不会继承这份权限。

### 破坏性请求

```text
linuxagent > 删除 /tmp/old_backup
LLM proposes: rm -rf /tmp/old_backup
Safety: CONFIRM, Rule: DESTRUCTIVE
```

批准只对这一次执行有效。下一条破坏性命令仍会再次确认。

### 被阻断的请求

```text
linuxagent > 彻底清空系统
LLM proposes: rm -rf /
Blocked: destructive command targeting root filesystem
```

命令会在策略阶段被拒绝，不会执行，也不会进入 HITL 审批。

### SSH 批量操作

在 `cluster.hosts` 配置主机，并确保 host key 已经在 `~/.ssh/known_hosts`
中。请求目标达到两台或更多主机时，LinuxAgent 会在扇出前展示批量确认，
包含命令、命中规则、主机列表和远端 profile 摘要。

```yaml
cluster:
  batch_confirm_threshold: 2
  known_hosts_path: ~/.ssh/known_hosts
  hosts:
    - name: web-1
      hostname: 192.0.2.11
      username: ops
      key_filename: ~/.ssh/id_ed25519
```

### 文件生成与修改

当你要求“新建脚本”或“修改配置”时，LinuxAgent 使用结构化 file patch
流程，而不是让模型通过 shell 重定向覆盖文件。planner 可以先用只读工具检查允许范围内的文件，
再返回包含目标文件、unified diff、风险说明和验证命令的 `FilePatchPlan`。
写入前会展示 diff；批准后的 patch 会事务化应用。完整说明见
[操作员安全模型](operator-safety.md)。

### 中断与恢复

未完成的确认节点会以私有权限保存。重启 CLI 后运行 `/resume`，选择对应会话，
LinuxAgent 会按同一 thread 重新打开未完成的审批。

## 审计日志

HITL 决策、执行、拒绝和相关元数据会以 hash-chained JSONL 追加到
`~/.linuxagent/audit.log`，权限为 `0o600`。`linuxagent audit verify` 借助 tip-hash
锚点 sidecar 检测就地篡改、尾部截断和整文件删除。

常用只读命令：

```bash
linuxagent audit verify
linuxagent audit summary
linuxagent audit inspect --limit 10
linuxagent audit inspect --show-commands
```

`inspect` 默认脱敏命令明细。只有显式传入 `--show-commands` 时，才会在现有脱敏规则处理后打印命令文本。

## 本地记忆与语言

本地文件系统记忆只是 advisory context，不是安全边界。它不能降低策略决策、
跳过 HITL、改变 sandbox enforcement、执行命令或修改审计记录。完全关闭记忆读写：

```yaml
memory:
  enabled: false
```

LinuxAgent 自有固定 UI 文案的运行时语言可在顶层设置：

```yaml
language: zh-CN  # zh-CN | en-US
```

该设置不会翻译命令输出、prompt 模板、审计字段名、tool 名称、policy rule id 或模型生成的回答。

## 下一步阅读

| 需求 | 链接 |
|---|---|
| Provider 配置 | [Provider 兼容矩阵](provider-matrix.md) |
| 操作员安全模型 | [操作员安全模型](operator-safety.md) |
| 威胁模型 | [威胁模型](threat-model.md) |
| 生产检查清单 | [生产就绪清单](production-readiness.md) |
| 红队用例 | [红队基线](../en/red-team.md) |
| 开发流程 | [开发指南](development.md) |
| 发布流程 | [发布指南](release.md) |
| v4.1 发布说明 | [v4.1.0](releases/v4.1.0.md) |
| 英文手册 | [English](../en/README.md) |

## 常见问题

**`linuxagent check` 提示配置必须是 `0600`。**
运行 `chmod 600 ~/.config/linuxagent/config.yaml`，并确认文件属于当前用户。

**提示 `api.api_key is required`。**
在当前生效配置中设置 `api.api_key`。bootstrap 后通常是 `LINUXAGENT_CONFIG`
指向的文件；如果某个工作区要用单独配置，请使用 `--config ./config.yaml`。

**`--yes` 可以跳过所有确认吗？**
不可以。命令级 `CONFIRM` 和 `BLOCK` 是安全边界。非交互上下文会自动拒绝确认，
而不是自动批准。

## 许可证

本项目使用 MIT License。
