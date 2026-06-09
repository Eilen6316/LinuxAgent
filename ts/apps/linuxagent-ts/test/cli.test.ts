import { chmod, mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { runCli } from "../src/cli.js";

describe("linuxagent-ts CLI", () => {
  it("runs check against explicit safe sample paths", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-cli-check-"));
    const auditDir = join(dir, "audit");
    const configPath = join(dir, "config.yaml");
    const policyPath = join(dir, "policy.yaml");
    await mkdir(auditDir);
    await writeFile(configPath, "api:\n  provider: fake\n", { mode: 0o600 });
    await chmod(configPath, 0o600);
    await writeFile(policyPath, "rules: []\n", { mode: 0o600 });
    const output: string[] = [];

    const exitCode = await runCli(
      [
        "check",
        "--config",
        configPath,
        "--policy",
        policyPath,
        "--audit",
        join(auditDir, "audit.log"),
      ],
      { stdout: output.push.bind(output) },
    );

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain("linuxagent-ts check: ok");
  });

  it("rejects incomplete check flags with usage text", async () => {
    const errors: string[] = [];

    const exitCode = await runCli(["check", "--config"], { stderr: errors.push.bind(errors) });

    expect(exitCode).toBe(2);
    expect(errors.join("\n")).toContain("--config requires a value");
  });

  it("dispatches chat", async () => {
    const output: string[] = [];

    const exitCode = await runCli(["chat"], { stdout: output.push.bind(output) });

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain("linuxagent-ts chat");
  });

  it("dispatches audit verify", async () => {
    const output: string[] = [];

    const exitCode = await runCli(["audit", "verify"], { stdout: output.push.bind(output) });

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain("linuxagent-ts audit verify");
  });

  it("rejects unknown commands with usage text", async () => {
    const errors: string[] = [];

    const exitCode = await runCli(["unknown"], { stderr: errors.push.bind(errors) });

    expect(exitCode).toBe(2);
    expect(errors.join("\n")).toContain("Usage: linuxagent-ts");
  });
});
