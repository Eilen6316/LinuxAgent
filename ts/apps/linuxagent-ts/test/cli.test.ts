import { chmod, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { AuditWriter } from "@linuxagent/audit";
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

  it.each([
    ["/new", "new"],
    ["/resume", "resume"],
    ["/tools", "tools"],
  ] as const)("routes chat slash input %s", async (input, expected) => {
    const output: string[] = [];

    const exitCode = await runCli(["chat", "--input", input], { stdout: output.push.bind(output) });

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain(`linuxagent-ts chat: ${expected}`);
  });

  it("runs chat input through the runtime port", async () => {
    const output: string[] = [];

    const exitCode = await runCli(["chat", "--input", "check kernel"], {
      stdout: output.push.bind(output),
    });

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain("linuxagent-ts chat: direct_answer");
  });

  it("fails closed for direct command chat input when execution is not configured", async () => {
    const output: string[] = [];

    const exitCode = await runCli(["chat", "--input", "!printf should-not-run"], {
      stdout: output.push.bind(output),
    });

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain("linuxagent-ts chat: direct_command blocked");
  });

  it("rejects incomplete chat input flags", async () => {
    const errors: string[] = [];

    const exitCode = await runCli(["chat", "--input"], { stderr: errors.push.bind(errors) });

    expect(exitCode).toBe(2);
    expect(errors.join("\n")).toContain("--input requires a value");
  });

  it("verifies a valid audit log", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-cli-audit-"));
    const auditPath = join(dir, "audit.log");
    await new AuditWriter(auditPath).append("hitl.decision", { decision: "approve" });
    const output: string[] = [];

    const exitCode = await runCli(["audit", "verify", auditPath], {
      stdout: output.push.bind(output),
    });

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain("linuxagent-ts audit verify: valid");
  });

  it("returns non-zero for tampered audit logs", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-cli-audit-"));
    const auditPath = join(dir, "audit.log");
    await new AuditWriter(auditPath).append("hitl.decision", { decision: "approve" });
    const text = await readFile(auditPath, "utf8");
    await writeFile(auditPath, text.replace("approve", "deny"), { mode: 0o600 });
    const output: string[] = [];

    const exitCode = await runCli(["audit", "verify", auditPath], {
      stdout: output.push.bind(output),
    });

    expect(exitCode).toBe(1);
    expect(output.join("\n")).toContain("invalid");
  });

  it("rejects audit verify without a path", async () => {
    const errors: string[] = [];

    const exitCode = await runCli(["audit", "verify"], { stderr: errors.push.bind(errors) });

    expect(exitCode).toBe(2);
    expect(errors.join("\n")).toContain("audit verify requires a path");
  });

  it("rejects unknown commands with usage text", async () => {
    const errors: string[] = [];

    const exitCode = await runCli(["unknown"], { stderr: errors.push.bind(errors) });

    expect(exitCode).toBe(2);
    expect(errors.join("\n")).toContain("Usage: linuxagent-ts");
  });
});
