# Quick Start

## 1. Bootstrap

```bash
./scripts/bootstrap.sh
source .venv/bin/activate
```

## 2. Configure

LinuxAgent reads configuration from `config.yaml`.

The normal local workflow is:

```bash
cp configs/example.yaml config.yaml
chmod 600 config.yaml
```

Set at least:

```yaml
api:
  api_key: "your-real-key"
```

## 3. Validate

```bash
linuxagent check
```

## 4. Start The CLI

```bash
linuxagent chat
```

## 5. Useful Dev Commands

```bash
make test
make lint
make type
make security
make harness
```
