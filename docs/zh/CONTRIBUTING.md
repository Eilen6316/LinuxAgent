# 贡献指南

感谢参与 LinuxAgent。这个项目涉及本地和远程 Linux 命令执行，因此 review 会
优先关注行为是否明确、测试是否充分、默认值是否保守。

## 开始之前

1. 阅读 [中文完整文档](README.md)、[开发指南](../en/development.md)
   和 [威胁模型](threat-model.md)。
2. 创建虚拟环境并安装开发依赖：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

3. 提 PR 前运行本地门禁：

```bash
make lint
make type
make test
make security
make harness
make verify-build
```

本地环境允许时，建议额外运行：

```bash
make integration
make optional-anthropic
```

## 安全规则

- 不要添加 `shell=True`。
- 不要用 `pattern in command` 这类字符串包含判断做命令安全。
- 不要重新引入 `paramiko.AutoAddPolicy`。
- 不要绕过 LLM 生成命令或破坏性命令的 Human-in-the-Loop。
- 不要记录密钥，也不要把未脱敏命令输出送入 LLM 路径。

如果改动涉及命令分类、HITL、SSH、审计、配置或脱敏，请补充直接覆盖真实
逻辑的测试，不要 mock 掉核心安全决策。

## 依赖规则

运行时依赖以 `pyproject.toml` 为准。`constraints.txt` 用于可复现安装和发布
验证；不要在多个地方手工维护版本，除非在 PR 中说明原因。

## Pull Request 要求

- 保持 scope 清晰，并说明对操作员可见的行为变化。
- 修改公共函数或工作流时补测试。
- 行为、配置、发布流程或安全语义变化时同步更新文档。
- 破坏性变更必须写迁移说明。
- 不要提交 `.work/`、`.codex/`、`config.yaml`、构建产物、缓存或密钥。

## Commit Message

使用简洁、描述行为的提交信息，例如：

```text
fix: guard system tool outputs
docs: add production readiness checklist
```

公开 commit message 不使用内部计划标签。
