# Plan 1 · 基础层（项目骨架 + 框架就绪）

**目标**：建立新项目骨架，配置系统、接口定义、依赖注入容器、LangChain/LangGraph 基础依赖全部就位。后续所有 Plan 以此骨架为基础增量演进；若需回改本层文件，必须在 `change/` 留痕。

**前置条件**：无
**交付物**：可 `pip install -e .` 安装、`python -m linuxagent --help` 不报错的空壳项目，LangChain/LangGraph 可正常 import

---

## Scope

### 1.1 目录结构

遵循 `design/architecture.md` §目录结构 定义的 **src-layout + 领域子包** 布局。本轮只落地「骨架 + 配置 + 接口 + 容器 + 日志」五块实体文件，其余子包只建空 `__init__.py` 占位。

#### 1.1.1 迁移旧代码（开工第一步）

```bash
mkdir -p legacy
git mv src legacy/src_v3
git mv linuxagent.py legacy/
git mv setup.py legacy/
git mv pyinstaller.spec legacy/
```

在 `legacy/README.md` 写明：
```markdown
# legacy/ · v3 冷藏区

- 不要修改本目录任何文件
- 不跑 lint / mypy / pytest
- v4.0.0 发版时整块删除
- 如需查阅 v3 行为，仅供参考
```

`.gitignore` 补上 linter 忽略项（可选，或者在 `pyproject.toml` 的 ruff/mypy 配置里 `exclude = ["legacy/"]`）。

#### 1.1.2 本轮新建文件（只列实际写入内容的文件）

```
src/linuxagent/
├── __init__.py                ← 只导出 __version__
├── __main__.py                ← `python -m linuxagent` → cli.main()
├── cli.py                     ← argparse 骨架，打印 --help
├── py.typed                   ← 空文件，PEP 561 标记
├── logger.py                  ← logging + JSON/彩色两种 handler
├── container.py               ← 依赖注入容器（手写简单版）
├── config/
│   ├── __init__.py
│   ├── models.py              ← 全部 Pydantic 模型
│   └── loader.py              ← YAML 加载 + 配置路径环境变量支持
└── interfaces/
    ├── __init__.py
    ├── llm_provider.py        ← LLMProvider ABC
    ├── executor.py            ← CommandExecutor ABC
    ├── ui.py                  ← UserInterface ABC
    └── service.py             ← BaseService ABC
```

#### 1.1.3 本轮只建占位 `__init__.py` 的子包

后续 Plan 会填充内容，本轮只保留空 `__init__.py` 让 import 不报错：

```
src/linuxagent/{app,graph,tools,providers,services,executors,cluster,intelligence,monitoring,ui}/__init__.py
```

#### 1.1.4 本轮配套的仓库级文件

| 文件 | 内容 |
|---|---|
| `pyproject.toml` | PEP 517/621，替代 `setup.py` |
| `Makefile` | `install` / `test` / `lint` / `type` / `harness` / `build` 目标 |
| `.pre-commit-config.yaml` | ruff / mypy / bandit / trailing-whitespace / detect-secrets |
| `CHANGELOG.md` | Keep a Changelog 格式，`[Unreleased]` 段预留 |
| `configs/default.yaml` | 内置默认值，`api_key` 留空，committed |
| `configs/example.yaml` | 带注释的完整样例，占位密钥，committed |
| `prompts/.gitkeep` | 目录占位，Plan 3 填充 |
| `tests/conftest.py` | 空骨架 + 一个 smoke test |
| `docs/.gitkeep` | 目录占位，Plan 6 填充 |
| `scripts/bootstrap.sh` | 一键建 venv + 安装开发依赖 + 初始化用户 `./config.yaml`（chmod 600） |
| `.github/workflows/ci.yml` | 最小 CI：安装 + mypy + smoke test |

**不创建** `.env` / `.env.example`（参见 `change/2026-04-23-config-yaml-only.md`）。
根目录 `./config.yaml` 作为用户本地覆盖，已在 `.gitignore` 中忽略。

### 1.2 Config 模型（`config/models.py`）

覆盖 `config.yaml` 全部配置节，无一遗漏：

| Pydantic 模型 | 对应 config.yaml 节 |
|---|---|
| `APIConfig` | `api`（含 `api_key: SecretStr`） |
| `SecurityConfig` | `security`（含 `session_whitelist_enabled: bool = true`） |
| `ClusterConfig` | `cluster`（含 `batch_confirm_threshold: int = 2`、`hosts: list[...]`） |
| `AuditConfig` | `audit`（含 `path: Path = ~/.linuxagent/audit.log`；无 `enabled` 字段，审计不可关闭） |
| `UIConfig` | `ui` |
| `LoggingConfig` | `logging` |
| `MonitoringConfig` | `monitoring` |
| `AnalyticsConfig` | `analytics` |
| `LogAnalysisConfig` | `log_analysis` |
| `IntelligenceConfig` | `intelligence` |
| `AppConfig` | 根，聚合所有子模型 |

- 所有模型 `model_config = ConfigDict(frozen=True)`
- 密钥字段用 `SecretStr`，取值时显式 `.get_secret_value()`
- 启动时 `AppConfig.model_validate(raw_dict)` 一次性验证，失败即退出
- **禁止** `os.environ` 读取配置值（R-SEC-04）

### 1.3 Config 加载器（`config/loader.py`）

#### 加载优先级

```
1. CLI 参数 --config <path>       （最高）
2. LINUXAGENT_CONFIG（环境变量）    仅指定路径
3. ./config.yaml                   当前目录
4. ~/.config/linuxagent/config.yaml XDG
5. configs/default.yaml            内置默认（最低）
```

高优先级覆盖低优先级；多个文件按顺序合并（深度合并，非替换）。

#### 文件权限与所有权校验

加载时对**任何用户提供的配置文件路径**都必须通过校验，**不以文件位置区分**：

- `--config <path>` 传入的路径（不论位置）
- `LINUXAGENT_CONFIG` 环境变量指向的路径
- `./config.yaml`（仓库根）
- `~/.config/linuxagent/config.yaml`（XDG）

**唯一豁免**：仓库内置模板 `configs/default.yaml` 和 `configs/example.yaml`（由 CI 的 detect-secrets hook 保证不含真实密钥）。

校验同时满足：

```python
def _verify_secure(path: Path) -> None:
    st = path.stat()
    mode = st.st_mode & 0o777
    if mode != 0o600:
        raise ConfigPermissionError(
            f"{path} must have permissions 0600, got {oct(mode)}. "
            f"Run: chmod 600 {path}"
        )
    if st.st_uid != os.getuid():
        raise ConfigPermissionError(
            f"{path} must be owned by current user (uid={os.getuid()}), "
            f"got uid={st.st_uid}"
        )
```

`configs/default.yaml` 和 `configs/example.yaml` 豁免权限检查（内置模板，不含真实密钥）。

#### 错误与提示

- 文件不存在：打印「如何从 `configs/example.yaml` 生成」的指引
- 权限不对：给出 `chmod 600` 精确命令
- 字段非法：Pydantic 错误 + 出错的 yaml 行号（使用 `ruamel.yaml` 解析时可得）

### 1.4 接口定义（`interfaces/`）

```python
# interfaces/llm_provider.py
class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, messages: list[Message], **kwargs) -> str: ...
    @abstractmethod
    async def stream(self, messages: list[Message], **kwargs) -> AsyncIterator[str]: ...

# interfaces/executor.py
class CommandExecutor(ABC):
    @abstractmethod
    async def execute(self, command: str) -> ExecutionResult: ...
    @abstractmethod
    def is_safe(self, command: str) -> SafetyResult: ...

# interfaces/service.py
class BaseService(ABC):
    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
```

### 1.5 依赖注入容器（`container.py`）

使用 `dependency-injector` 库或手写简单容器。  
容器负责构造所有服务实例并注入依赖，`Agent` 只接收已构造好的对象。

### 1.6 日志配置（`logger.py`）

- 支持 JSON 结构化日志（生产）和彩色控制台日志（开发）
- 日志级别从 `AppConfig.logging.level` 读取
- 禁止在模块内调用 `basicConfig`
- 预留 LangSmith 追踪钩子（通过环境变量 `LANGCHAIN_TRACING_V2` 启用，本轮不启用）

### 1.7 框架依赖锁定

`pyproject.toml` 写入本轮必需的框架依赖（即使后续 Plan 才真正使用）：

```toml
[project]
dependencies = [
    "pydantic>=2.7,<3.0",
    "pyyaml>=6.0,<7.0",
    "langchain-core>=0.3,<0.4",
    "langgraph>=0.2,<0.3",
    "rich>=13.0,<15.0",
    "prompt_toolkit>=3.0,<4.0",
]
```

本轮仅做 `import` smoke test，不实现业务：
```python
# tests/unit/test_framework_ready.py
def test_langchain_importable():
    from langchain_core.messages import HumanMessage
    assert HumanMessage(content="ok").content == "ok"

def test_langgraph_importable():
    from langgraph.graph import StateGraph, END
    assert END is not None
```

### 1.8 pyproject.toml 替代 setup.py

原版 `setup.py` 混入构建工具（`pyinstaller`、`setuptools`）到 `install_requires`，本轮彻底替换为 PEP 517 `pyproject.toml`：

- 运行时依赖 → `[project.dependencies]`
- 开发依赖 → `[project.optional-dependencies.dev]`
- 打包依赖 → `[project.optional-dependencies.pyinstaller]`
- CLI 入口 → `[project.scripts]`

---

## 验收标准

### 目录迁移

- [ ] 旧代码完整移入 `legacy/`，根目录和 `src/linuxagent/` 不含 v3 残留
- [ ] `legacy/README.md` 声明「不要修改 / 不跑 lint」
- [ ] `ruff`、`mypy`、`pytest` 的 exclude 配置均忽略 `legacy/`

### 安装与入口

- [ ] `pip install -e .` 成功，无警告
- [ ] `python -m linuxagent --help` 显示帮助，不报错
- [ ] `linuxagent --help`（pyproject 注册的 console script）等价工作
- [ ] `pyproject.toml` 完整取代 `setup.py`（`setup.py` 不再在根目录）

### 配置

- [ ] `AppConfig` 能解析 `configs/default.yaml` 全部字段
- [ ] 加载优先级：CLI > env path > `./config.yaml` > XDG > `configs/default.yaml`，能合并覆盖
- [ ] `./config.yaml` 权限不是 `0600` 时拒绝启动并给出 `chmod 600` 提示
- [ ] 文件所有者非当前用户时拒绝启动
- [ ] `--config /tmp/foo.yaml`（任意路径）权限/所有者不合规时同样拒绝启动
- [ ] `configs/default.yaml` 和 `configs/example.yaml` 豁免权限检查，仍可被加载合并
- [ ] 传入非法配置（如 `api.timeout: "abc"`）时启动失败并打印明确错误，定位到 yaml 行号
- [ ] 密钥字段使用 `SecretStr`，`__repr__` / 日志 / JSON 序列化均不暴露原值
- [ ] 无 `.env` / `.env.example` 文件存在于仓库根

### 框架就绪

- [ ] `tests/unit/test_framework_ready.py` 通过（LangChain / LangGraph 可正常导入）
- [ ] `from linuxagent.interfaces import LLMProvider, CommandExecutor` 成功

### 质量门禁

- [ ] `mypy src/linuxagent/` 零错误
- [ ] `ruff check src/linuxagent/` 零告警
- [ ] 所有接口类有 docstring
- [ ] `pre-commit run --all-files` 全绿
- [ ] `make test` / `make lint` / `make type` 均可执行

### CI

- [ ] 首条 GitHub Actions 运行通过（安装 + mypy + smoke test）

---

<!-- 完成记录（完成后追加） -->
