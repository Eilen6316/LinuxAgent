# Skill Manifests

LinuxAgent Skills are declarative local YAML manifests. They extend planner
guidance without adding executable plugin code.

## Configuration

Skills are disabled by default:

```yaml
skills:
  enabled: false
  manifests: []
```

Enable them by listing local manifest files:

```yaml
skills:
  enabled: true
  manifests:
    - ./skills/disk-inspection.yaml
```

When `skills.enabled: true`, at least one manifest path is required. Paths are
expanded with the same config path rules as the rest of LinuxAgent.

Run `linuxagent check` after enabling Skills. The check command loads every
manifest, validates schema, and reports a summary such as `skills=1 manifests`.
Missing files, invalid YAML, or unknown fields make the check fail before chat
starts.

## Manifest Schema

```yaml
name: disk-pack
version: "1.0"
description: Disk inspection guidance
planner_guidance: Prefer df before du for broad filesystem checks.
permissions:
  - filesystem.inspect
```

Supported fields:

- `name`
- `version`
- `description`
- `planner_guidance`
- `permissions`

Skill guidance is injected into planner context with a source label such as
`Skill guidance from disk-pack@1.0`. It is advisory only; it does not route or
execute requests by itself.

## Safety Boundary

Skills cannot define Python hooks, shell hooks, download steps, or custom
execution backends. Unknown manifest fields fail validation.
