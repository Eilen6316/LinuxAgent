# legacy/ — v3 冷藏区

本目录保存 LinuxAgent v3 的全部源码，作为 v4 重写过程中的历史参考。

## 规则

- **不要修改** 本目录任何文件
- **不跑** `ruff` / `mypy` / `pytest` / `bandit`（已在 pyproject.toml / Makefile / pre-commit 配置中 exclude）
- **不 import** —— v4 代码若需参考 v3 实现，请阅读后用新结构重写，不要直接调用
- **v4.0.0 发版时整块删除** —— 届时本目录会从仓库中移除

## 迁移映射

| v3 位置 | 替代位置（v4，规划中） |
|---|---|
| `legacy/linuxagent.py` | `src/linuxagent/cli.py` + `python -m linuxagent` |
| `legacy/setup.py` | `pyproject.toml`（PEP 517/621） |
| `legacy/requirements.txt` | `pyproject.toml` 的 `[project.dependencies]` |
| `legacy/pyinstaller.spec` | `pyproject.toml` 的 `[project.optional-dependencies.pyinstaller]` |
| `legacy/src_v3/agent.py` (4710 行) | `src/linuxagent/app/agent.py`（≤300 行）+ `src/linuxagent/graph/`（LangGraph 状态机） |
| `legacy/src_v3/config.py` | `src/linuxagent/config/models.py`（Pydantic v2） |
| `legacy/src_v3/executors/linux_command.py` | `src/linuxagent/executors/linux_executor.py`（零 `shell=True`） |
| `legacy/src_v3/cluster/ssh_manager.py` | `src/linuxagent/cluster/ssh_manager.py`（`RejectPolicy`） |
| `legacy/src_v3/providers/*.py` | `src/linuxagent/providers/`（基于 LangChain ChatModel） |
| `legacy/src_v3/intelligence/*.py` | `src/linuxagent/intelligence/` + `tools/intelligence_tools.py`（LangChain `@tool`） |
| `legacy/src_v3/ui/console.py` | `src/linuxagent/ui/console.py`（实现 `UserInterface`） |

## 为什么 v3 被整体替换

根据 `.work/design/architecture.md` 与 2026-04-23 的代码审查：

1. 多处 `shell=True` + 未校验 LLM 输出 → 命令注入（Critical）
2. 危险命令过滤用字符串包含，正则形同虚设（Critical）
3. SSH `AutoAddPolicy`，无主机密钥验证（Critical）
4. `agent.py` 4710 行 God Object，无法安全渐进重构（High）
5. 零单元测试，无法回归验证改动（High）
6. `AlertManager.start()` 方法缺失会在运行时崩溃（High）

维护 / 补丁成本超过重写成本，故 v4 采用 LangGraph + Pydantic v2 + 分层 + 依赖注入的全新架构。
