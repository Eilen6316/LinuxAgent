# Quick Start

This page gets a fresh checkout to the first audited, operator-approved
LinuxAgent turn.

## Install

```bash
git clone https://github.com/Eilen6316/LinuxAgent.git
cd LinuxAgent
./scripts/bootstrap.sh
```

The bootstrap script installs project dependencies in `.venv`, creates a
user-level `~/.local/bin/linuxagent` launcher, and writes
`LINUXAGENT_CONFIG=$HOME/.config/linuxagent/config.yaml` to your shell profile.
Open a new shell or run `source ~/.bashrc` before starting `linuxagent` from
another directory. If the command is not found, add `~/.local/bin` to `PATH`.

## Minimal Config

Edit `~/.config/linuxagent/config.yaml` and configure one provider.

Remote provider:

```yaml
api:
  provider: deepseek
  api_key: "your-real-key"
```

Local OpenAI-compatible provider:

```yaml
api:
  provider: ollama
  base_url: http://127.0.0.1:11434/v1
  model: llama3.1
  api_key: ""
  token_parameter: max_tokens
```

Keep the config file owned by your user and private:

```bash
chmod 600 ~/.config/linuxagent/config.yaml
```

## Check

```bash
linuxagent check
```

Fix any reported config or provider issue before continuing.

## Start

```bash
linuxagent
```

Try a read-only first request:

```text
check the Linux version
```

When LinuxAgent proposes the first LLM-generated command, the confirmation menu
lets you run it once, allow the same argv command shape for this conversation
and the same `/resume` thread, or refuse it.

## Continue Or Reset

Use `/resume` to reopen a saved conversation. Use `/new` to start a fresh
conversation inside the running CLI.
