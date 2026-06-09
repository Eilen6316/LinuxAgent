# 快速开始

本页只覆盖从全新 checkout 到第一次经过审计、由操作员确认的 LinuxAgent 操作。

## 安装

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh
```

bootstrap 脚本会把依赖安装到当前 checkout 的 `.venv`，创建用户级
`~/.local/bin/linuxagent` 启动器，并把
`LINUXAGENT_CONFIG=$HOME/.config/linuxagent/config.yaml` 写入 shell profile。
从其他目录启动前，请打开一个新 shell，或运行 `source ~/.bashrc`。如果找不到
`linuxagent` 命令，请把 `~/.local/bin` 加入 `PATH`。

## 最小配置

编辑 `~/.config/linuxagent/config.yaml`，配置一个 provider。

远程 provider：

```yaml
api:
  provider: deepseek
  api_key: "your-real-key"
```

本地 OpenAI-compatible provider：

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

确保配置文件归当前用户所有，并且权限是私有的：

```bash
chmod 600 ~/.config/linuxagent/config.yaml
```

## 检查

```bash
linuxagent check
```

如果检查报告配置或 provider 问题，请先修复再继续。

## 启动

```bash
linuxagent
```

第一次可以先尝试只读请求：

```text
check the Linux version
```

当 LinuxAgent 提出第一条由 LLM 生成的命令时，确认菜单允许你只执行一次、
在当前对话和同一 `/resume` 线程中允许相同 argv 命令形态，或拒绝执行。

## 继续或重置

使用 `/resume` 重新打开已保存的对话。使用 `/new` 在当前 CLI 中开始一个新对话。
