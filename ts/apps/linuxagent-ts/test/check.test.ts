import { chmod, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { runCheck } from "../src/commands/check.js";

describe("linuxagent-ts check", () => {
  it("rejects group-readable config files", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-check-"));
    const configPath = join(dir, "config.yaml");
    const policyPath = join(dir, "policy.yaml");
    await writeFile(configPath, localProviderConfig(), { mode: 0o644 });
    await chmod(configPath, 0o644);
    await writeFile(policyPath, "rules: []\n", { mode: 0o600 });

    const result = await runCheck({ configPath, policyPath, auditPath: join(dir, "audit.log") });

    expect(result.ok).toBe(false);
    expect(result.checks.find((check) => check.name === "config_mode")?.ok).toBe(false);
  });

  it("accepts private config files and accessible audit parent directories", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-check-"));
    const auditDir = join(dir, "audit");
    const configPath = join(dir, "config.yaml");
    const policyPath = join(dir, "policy.yaml");
    await mkdir(auditDir);
    await writeFile(configPath, localProviderConfig(), { mode: 0o600 });
    await chmod(configPath, 0o600);
    await writeFile(policyPath, "rules: []\n", { mode: 0o600 });

    const result = await runCheck({
      configPath,
      policyPath,
      auditPath: join(auditDir, "audit.log"),
    });

    expect(result.ok).toBe(true);
    expect(result.checks.map((check) => check.name)).toEqual([
      "config",
      "config_mode",
      "react_provider",
      "policy",
      "audit_parent",
    ]);
  });

  it("loads the compiled check command after build", async () => {
    const distUrl = new URL("../dist/src/commands/check.js", import.meta.url).href;
    const distCheck = (await import(distUrl)) as { runCheckCommand?: unknown };

    expect(typeof distCheck.runCheckCommand).toBe("function");
  });
});

function localProviderConfig(): string {
  return [
    "api:",
    "  provider: ollama",
    "  base_url: http://127.0.0.1:11434",
    "  model: llama3.1",
    "  api_key: ''",
    "",
  ].join("\n");
}
