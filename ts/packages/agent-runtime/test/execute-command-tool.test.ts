import { describe, expect, it } from "vitest";
import type { SandboxExecutionResult, SandboxSpec } from "../../sandbox/src/index.js";
import { type CommandExecutorPort, executeCommandTool } from "../src/execute-command-tool.js";
import type { LinuxAgentToolGate } from "../src/tool-gate.js";

class StubGate {
  readonly calls: Parameters<LinuxAgentToolGate["beforeToolCall"]>[0][] = [];

  constructor(private readonly result: Awaited<ReturnType<LinuxAgentToolGate["beforeToolCall"]>>) {}

  async beforeToolCall(
    context: Parameters<LinuxAgentToolGate["beforeToolCall"]>[0],
  ): Promise<Awaited<ReturnType<LinuxAgentToolGate["beforeToolCall"]>>> {
    this.calls.push(context);
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
    const gate = new StubGate(undefined);

    const result = await executeCommandTool({
      args: { argv: ["printf", "ok"] },
      sandbox: { profile: "noop", timeoutMs: 1000 },
      gate,
      executor,
    });

    expect(executor.calls).toHaveLength(1);
    expect(gate.calls[0]).toMatchObject({
      args: {
        sandbox: {
          profile: "noop",
          timeoutMs: 1000,
        },
      },
    });
    expect(result.executed).toBe(true);
    if (!result.executed) {
      throw new Error("expected command to execute");
    }
    expect(result.sandbox.metadata).toEqual({ profile: "noop" });
    expect(result.modelText).not.toContain("secret-token-value");
    expect(result.modelText).toContain("[REDACTED]");
    expect(result.redacted).toBe(true);
  });
});
