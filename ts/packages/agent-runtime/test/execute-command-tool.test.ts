import { describe, expect, it } from "vitest";
import type { SandboxExecutionResult, SandboxSpec } from "../../sandbox/src/index.js";
import { type CommandExecutorPort, executeCommandTool } from "../src/execute-command-tool.js";
import type { LinuxAgentToolGate } from "../src/tool-gate.js";

class StubGate {
  constructor(private readonly result: Awaited<ReturnType<LinuxAgentToolGate["beforeToolCall"]>>) {}

  async beforeToolCall(): Promise<Awaited<ReturnType<LinuxAgentToolGate["beforeToolCall"]>>> {
    return this.result;
  }
}

class RecordingExecutor implements CommandExecutorPort {
  calls: Array<{ argv: readonly string[]; spec: SandboxSpec }> = [];

  async execute(argv: readonly string[], spec: SandboxSpec): Promise<SandboxExecutionResult> {
    this.calls.push({ argv, spec });
    return {
      enforced: false,
      runner: "noop",
      exitCode: 0,
      stdout: "Authorization: Bearer secret-token-value",
      stderr: "",
      timedOut: false,
      metadata: { profile: spec.profile },
    };
  }
}

describe("executeCommandTool", () => {
  it("does not execute when the gate blocks", async () => {
    const executor = new RecordingExecutor();

    const result = await executeCommandTool({
      args: { argv: ["rm", "-rf", "/"] },
      sandbox: { profile: "noop", timeoutMs: 1000 },
      gate: new StubGate({ block: true, reason: "blocked" }),
      executor,
    });

    expect(result.executed).toBe(false);
    if (result.executed) {
      throw new Error("expected command to be blocked");
    }
    expect(result.blockedReason).toBe("blocked");
    expect(executor.calls).toHaveLength(0);
  });

  it("executes through executor and returns redacted model-facing output", async () => {
    const executor = new RecordingExecutor();

    const result = await executeCommandTool({
      args: { argv: ["printf", "ok"] },
      sandbox: { profile: "noop", timeoutMs: 1000 },
      gate: new StubGate(undefined),
      executor,
    });

    expect(executor.calls).toHaveLength(1);
    expect(result.executed).toBe(true);
    expect(result.modelText).not.toContain("secret-token-value");
    expect(result.modelText).toContain("[REDACTED]");
    expect(result.redacted).toBe(true);
  });
});
