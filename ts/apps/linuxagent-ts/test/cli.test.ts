import { describe, expect, it } from "vitest";

import { runCli } from "../src/cli.js";

describe("linuxagent-ts CLI", () => {
  it("dispatches check", async () => {
    const output: string[] = [];

    const exitCode = await runCli(["check"], { stdout: output.push.bind(output) });

    expect(exitCode).toBe(0);
    expect(output.join("\n")).toContain("linuxagent-ts check");
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
