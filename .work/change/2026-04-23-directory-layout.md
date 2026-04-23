# 采用 src-layout 与领域导向目录结构

- **日期**：2026-04-23
- **类型**：设计变更
- **影响范围**：`design/architecture.md` 新增「目录结构」§；`plan/Plan1.md` §1.1 重写
- **决策者**：项目所有者

## 背景

初版 Plan 1 的目录结构只列了 `linuxagent/` 包，没有明确：
- 包应该放在仓库根还是 `src/` 下
- 旧 v3 代码（当前 `src/` 下的扁平模块）如何与 v4 并存
- prompts、harness 场景、配置样例等非代码资源的存放位置
- Python 现代项目的周边文件（pyproject.toml、Makefile、.env.example 等）

当前 `src/` 目录不是 PEP 标准的 src-layout，而是扁平包目录：
```
src/
├── agent.py          ← 顶层模块
├── config.py
├── providers/        ← 各自独立包
└── ...
```

这种布局会让 `pip install` 后的导入路径与开发时不一致，也是 v3 混用绝对导入（`from src.xxx`）和相对导入的根本原因。

## 新决策

### 1. 采用 PyPA 推荐的 src-layout

```
src/
└── linuxagent/       ← 单一包，名称即发布名
    ├── __init__.py
    └── ...
```

好处：
- `pip install -e .` 后导入路径与开发时完全一致
- 防止 `python -c "import linuxagent"` 意外拾取仓库根目录的同名文件
- 与 PyPA 官方样例一致，工具链友好

### 2. 旧 v3 代码整体移入 `legacy/`

开工 Plan 1 第一步：
```bash
mkdir -p legacy
git mv src legacy/src_v3
git mv linuxagent.py legacy/
git mv setup.py legacy/
git mv pyinstaller.spec legacy/
```

`legacy/` 目录：
- 加入 `.gitignore` 的 `linting` 豁免（不跑 mypy / ruff）
- 根目录 README 里标注「legacy/，不要修改，v4.0.0 发布时删除」
- 新代码路径完全不与之重叠

### 3. 领域导向的子包结构（替代纯技术分层）

```
src/linuxagent/
├── app/          ← 应用层（瘦协调器）
├── graph/        ← LangGraph 状态机
├── tools/        ← LangChain @tool 定义
├── providers/    ← LLM Provider
├── services/     ← 核心业务服务
├── executors/    ← 命令执行（子进程沙箱）
├── cluster/      ← SSH 集群
├── intelligence/ ← 智能模块（学习 / 推荐 / 语义）
├── monitoring/   ← 系统监控
├── ui/           ← 用户界面
├── config/       ← Pydantic 配置模型
├── interfaces/   ← ABC / Protocol
├── logger.py
├── container.py  ← 依赖注入
├── __main__.py
├── cli.py
└── py.typed      ← PEP 561 类型标记
```

### 4. 代码之外的资源独立存放

| 目录 | 内容 | 为什么不塞代码里 |
|---|---|---|
| `prompts/` | Prompt 模板 (`.md` / `.txt`) | Prompt 需要被产品、测试、运维独立迭代 |
| `configs/` | `default.yaml` + `example.yaml` | 配置样例需要版本化但不参与导入 |
| `tests/harness/scenarios/` | YAML 场景文件 | Harness 场景与代码解耦，可由非开发者贡献 |
| `docs/` | 用户与开发文档 | README 太大时拆出 |
| `scripts/` | Shell 脚本（bootstrap、release） | 不是 Python 包的一部分 |
| `.github/workflows/` | CI/CD | GitHub 标准位置 |

### 5. 现代 Python 周边文件

| 文件 | 作用 |
|---|---|
| `pyproject.toml` | 替代 `setup.py`（PEP 517/621） |
| `Makefile` | 常用命令：`make test`、`make lint`、`make harness` |
| `.env.example` | 环境变量模板（`LINUXAGENT_API_KEY=` 等） |
| `CHANGELOG.md` | Keep a Changelog 格式 |
| `LICENSE` | 开源许可（沿用原仓库） |
| `py.typed` | PEP 561，告诉下游类型检查器本包有类型 |

## 影响

- **受影响文档**：
  - `design/architecture.md` 新增「目录结构」§（本变更一并更新）
  - `plan/Plan1.md` §1.1 整体重写为新布局（本变更一并更新）
  - Plan 2–6 中的路径表述统一为 `src/linuxagent/...`

- **受影响代码**：旧 `src/` 将在 Plan 1 开工时被 `git mv` 到 `legacy/src_v3/`

- **受影响构建**：`setup.py` → `pyproject.toml`；`pip install -e .` 命令不变

## 是否向后兼容

**否** —— 旧 `src.xxx` 绝对导入路径失效。由于旧代码整体进 `legacy/` 且不再维护，不提供迁移路径。新 v4 使用 `linuxagent.xxx` 作为唯一公开导入路径。
