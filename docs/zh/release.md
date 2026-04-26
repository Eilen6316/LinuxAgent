# 发布指南

## 本地检查清单

打 tag 前运行：

```bash
make test
make lint
make type
make security
python -m tests.harness.runner --scenarios tests/harness/scenarios
python -m pip check
make verify-build
```

wheel 验证步骤会构建 wheel，在临时虚拟环境中安装运行时依赖，检查
`linuxagent --help`，并确认打包后的 config、prompt、runbook 数据存在。默认使用
PyPI；如需私有镜像，可设置 `LINUXAGENT_PIP_INDEX_URL`。

可选集成冒烟检查：

```bash
make integration
make optional-anthropic  # 需要先 pip install -e '.[anthropic,dev]'
```

这些检查依赖本地环境是否满足集成测试和可选 provider extra 的条件，不属于默认
CI 门禁。

## 版本叙事

所有公开位置统一使用同一套发布定位：

> LinuxAgent v4.0.0 是重写后的第一个正式版本。它用基于 LangGraph 的、
> 策略驱动、可审计 CLI 替代旧原型，定位为受控的人机协同 Linux 运维工具。

建议 GitHub About 字段：

- Description: `LLM-driven Linux operations assistant CLI with mandatory HITL safety, policy engine, runbooks, SSH guards, and audit trails.`
- 中文描述：`LLM 驱动、强制 HITL、人机确认、策略引擎、Runbook、SSH 防护和审计日志的 Linux 运维 CLI。`
- Website: `https://github.com/Eilen6316/LinuxAgent#readme`
- Topics: `linux`, `ops`, `llm`, `agent`, `langgraph`, `cli`, `hitl`, `runbooks`, `ssh`, `audit`

## 依赖 Constraints

`constraints.txt` 来自已验证的 release 环境，并随 release 提交。可用于可复现安装：

```bash
pip install -c constraints.txt linuxagent
pip install -c constraints.txt -e ".[dev]"
```

完整门禁通过后重新生成：

```bash
pip-compile pyproject.toml --extra dev --extra anthropic --extra pyinstaller --strip-extras --index-url https://pypi.org/simple --output-file constraints.txt
```

## 预期产物

- `dist/*.whl`
- `dist/*.tar.gz`
- CI coverage artifact 中的 `coverage.xml` 和 `htmlcov/`

## 打 Tag 发布

```bash
git tag v4.0.0
git push origin v4.0.0
```

GitHub Actions release workflow 会构建产物，并使用 `docs/releases/v4.0.0.md`
作为 GitHub Release 正文。中文发布说明位于 `docs/zh/releases/v4.0.0.md`。
