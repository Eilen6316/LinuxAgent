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
</div>

LinuxAgent 是一个面向 Linux 运维场景的 LLM CLI 助手，核心目标是把自然语言交互、命令安全、人机确认和可测试编排放到同一条清晰链路里。

当前仓库中的主实现是基于 `LangGraph`、`LangChain`、`Pydantic v2` 重写后的 `v4` 架构。

## 为什么要重写

之前的设计存在几个根本问题：

- 一个过大的 Agent 对象同时承担意图理解、命令执行、UI、SSH、监控等职责
- 模型生成命令的安全边界不够硬
- SSH 信任策略不够严格
- 几乎没有可靠测试，重构风险高
- 交互流程、执行策略、基础设施耦合严重

`v4` 的目标不是“修补旧实现”，而是把系统拆成明确边界的小模块，再用状态机把流程重新接起来。

## 架构对比

| 维度 | 旧设计 | 当前 `v4` |
|---|---|---|
| 编排方式 | 大型 Agent 内部流程控制 | `LangGraph` 状态机节点编排 |
| 命令安全 | 零散检查 | token 级 `SAFE / CONFIRM / BLOCK` 分类 |
| 人工确认 | 逻辑混在业务里 | 基于 `interrupt()` 的 HITL 节点 |
| SSH | 与应用流程耦合 | 独立 cluster/service 边界 |
| 配置 | 更容易被绕过 | `Pydantic v2` fail-fast |
| 智能能力 | 模块化不足 | learner、语义增强、推荐、tool-calling |
| UI | 与 Agent 强耦合 | `ConsoleUI` 独立实现 `UserInterface` |
| 测试 | 保护不足 | unit、integration、harness、CI 红线门禁 |
| 打包发布 | 旧布局 | `pyproject.toml` + wheel/sdist + release workflow |

## 功能对比

| 功能 | 旧版本 | 当前 `v4` |
|---|---|---|
| 自然语言转命令 | 基础能力 | prompt + tools + provider 协作 |
| 模型命令首次确认 | 不完整 | 已强制执行 |
| 破坏性命令重复确认 | 不完整 | 已强制执行 |
| 集群批量确认 | 边界不清 | graph 层统一控制 |
| 审计日志 | 能力有限 | JSONL append-only 审计 |
| 会话白名单 | 规则弱 | 与破坏性命令策略联动 |
| 上下文管理 | 简单历史 | checkpoint 感知 + 压缩窗口 |
| 智能推荐 | 思路为主 | learner 与 intelligence tools 已接线 |
| 端到端场景验证 | 无 | YAML harness 覆盖普通/危险/HITL/集群场景 |

## 仓库结构

```text
src/linuxagent/     当前生效的 v4 包
tests/unit/         单元测试
tests/integration/  可选集成测试
tests/harness/      YAML 场景驱动 harness
configs/            默认配置与示例配置
prompts/            运行时 Prompt
docs/               使用与发布文档
scripts/            初始化与校验脚本
```

## 安装方式

### 开发环境初始化

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
```

### 手动安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp configs/example.yaml config.yaml
chmod 600 config.yaml
```

## 配置说明

LinuxAgent 通过 `config.yaml` 读取配置。

最小配置至少需要：

```yaml
api:
  api_key: "your-real-key"
```

配置校验：

```bash
linuxagent check
```

## 使用教程

### 启动 CLI

```bash
linuxagent chat
```

### 一次完整交互会发生什么

1. 你输入自然语言任务。
2. LinuxAgent 生成候选命令。
3. 安全层把命令分类为 `SAFE`、`CONFIRM` 或 `BLOCK`。
4. 需要确认时，UI 会展示命令、规则来源和批量主机范围。
5. 命令执行后，结果会再整理成更适合运维人员阅读的输出。

### 示例输入

- `查看 /var 的磁盘占用`
- `检查 nginx 服务状态`
- `在日志里找 ssh 登录失败记录`
- `在所有主机上执行 uptime`

### 常用开发命令

```bash
make test
make lint
make type
make security
make harness
make build
```

## 安全模型

- 模型生成命令首次执行必须确认
- 破坏性命令不会因为之前确认过就跳过确认
- 批量集群操作达到阈值后必须确认
- 无 TTY 环境下确认请求自动拒绝
- 所有 HITL 事件都写入 `~/.linuxagent/audit.log`

## 构建与发布

本地发布链路：

```bash
python -m tests.harness.runner --scenarios tests/harness/scenarios
python -m build --no-isolation
./scripts/verify_wheel_install.sh
```

正式发布：

```bash
git tag v4.0.0
git push origin v4.0.0
```

## 文档

- [Quick Start](docs/quickstart.md)
- [Development Guide](docs/development.md)
- [Release Guide](docs/release.md)

## License

MIT
