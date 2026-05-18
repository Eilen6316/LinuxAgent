# 发布指南

LinuxAgent 的正式发布包含两个出口：

- GitHub Release：附带 wheel 和 sdist。
- PyPI：通过 GitHub Actions + PyPI Trusted Publishing 发布。

## 维护者首次配置

首次发布到 PyPI 前，在 PyPI 配置 Trusted Publishing：

| 字段 | 值 |
|---|---|
| PyPI project | `linuxagent` |
| Owner | `Eilen6316` |
| Repository | `LinuxAgent` |
| Workflow | `release.yml` |
| Environment | `pypi` |

workflow 使用 GitHub OIDC，不需要保存 PyPI API token secret。

## 本地检查清单

打 tag 前运行：

```bash
make release-preflight
```

`make release-preflight` 会检查版本一致性、lint、类型检查、安全红线、单元测试、
sandbox 测试、集成测试、red-team 策略测试、YAML harness 和构建产物验证。请在
release 分支的干净工作树中运行。

release 检查会校验 `pyproject.toml`、`src/linuxagent/__init__.py`、
`CHANGELOG.md`、中文 changelog 和 release notes 是否指向同一版本。tag dry-run：

```bash
python scripts/release_check.py --versions --tag v4.1.0
```

产物验证步骤会构建 wheel 和 sdist，检查 wheel/sdist metadata，拒绝 `.work/`、
本地 `config.yaml`、缓存文件和 bytecode 进入产物，然后在临时虚拟环境安装 built
wheel。它会检查 `linuxagent --version`、`linuxagent --help`、`linuxagent check`，
并确认打包后的 config、policy、prompt 和 locale 数据存在。隔离 wheel
安装态还会校验 `zh-CN` / `en-US` locale catalog 可以加载且 key parity 一致。
默认使用 PyPI；如需私有镜像，可设置 `LINUXAGENT_PIP_INDEX_URL`。

国内网络较慢时，可用国内镜像运行同一套验证：

```bash
LINUXAGENT_PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
LINUXAGENT_PIP_TIMEOUT=120 \
make verify-build
```

可选集成冒烟检查：

```bash
make integration
make optional-anthropic  # 需要先 pip install -e '.[anthropic,dev]'
```

可选 provider extra 依赖本地环境是否满足条件。标准 integration suite 已包含在
`make release-preflight` 中。

## 版本叙事

所有公开位置统一使用同一套发布定位：

> LinuxAgent v4.1.0 是一次安全深度版本。它把 v4 的命令安全边界做得更容易被攻击、
> 被度量、被验证，也更容易被其他 agent 客户端复用。

建议 GitHub About 字段：

- Description: `LLM-driven Linux operations assistant CLI with mandatory HITL safety, policy engine, SSH guards, and audit trails.`
- 中文描述：`LLM 驱动、强制 HITL、人机确认、策略引擎、SSH 防护和审计日志的 Linux 运维 CLI。`
- Website: `https://github.com/Eilen6316/LinuxAgent#readme`
- Topics: `linux`, `ops`, `llm`, `agent`, `langgraph`, `cli`, `hitl`, `ssh`, `audit`

## 依赖 Constraints

`constraints.txt` 来自已验证的 release 环境，并随 release 提交。可用于可复现安装：

```bash
pip install -c constraints.txt linuxagent
pip install -c constraints.txt -e ".[dev]"
```

完整门禁通过后重新生成：

```bash
pip-compile pyproject.toml --extra dev --extra anthropic --extra pyinstaller --strip-extras --no-emit-trusted-host --index-url https://pypi.org/simple --output-file constraints.txt
```

## 预期产物

- `dist/*.whl`
- `dist/*.tar.gz`
- CI coverage artifact 中的 `coverage.xml` 和 `htmlcov/`

## 产物来源

release workflow 从 tag commit 构建产物，先运行 `make verify-build` 验证 wheel
安装路径，再把同一批 `dist/*.whl` 和 `dist/*.tar.gz` 上传到 GitHub Release 和
PyPI。

发布后验证：

```bash
python -m pip install --upgrade linuxagent
linuxagent --version
linuxagent --help
```

如果 PyPI 发布前 GitHub Release 已创建但 workflow 失败，删除 GitHub Release 和
tag，修复 release commit 后重新推送 tag。如果 PyPI 已接受该版本，不要覆盖产物；
改发新的 patch 版本，并在 release notes 记录回滚或被替代的产物。

## 打 Tag 发布

```bash
python scripts/release_check.py --versions --tag v4.1.0
git tag -s v4.1.0 -m "v4.1.0"
git push origin v4.1.0
```

GitHub Actions release workflow 会构建产物，并使用 `docs/releases/<tag>.md`
作为 GitHub Release 正文。中文发布说明位于 `docs/zh/releases/<tag>.md`。
同一个 workflow 会通过 Trusted Publishing 发布到 PyPI。

## 发布检查清单

- `pyproject.toml` 版本与 tag 一致。
- `src/linuxagent/__init__.py` 版本与 `pyproject.toml` 一致。
- `CHANGELOG.md`、中文 changelog 和 release notes 记录了用户可见变化。
- `constraints.txt` 已刷新，或明确说明本次无需变更。
- `make release-preflight` 在本地或 CI 通过。
- GitHub Release 包含 wheel 和 sdist。
- PyPI 页面显示新版本。
- 全新虚拟环境可以运行 `linuxagent --version`、`linuxagent --help` 和
  `linuxagent check`。
