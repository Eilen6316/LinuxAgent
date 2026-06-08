import { describe, expect, it } from "vitest";
import { PolicyEngine } from "../../policy/src/index.js";
import type { SandboxExecutionResult, SandboxSpec } from "../../sandbox/src/index.js";
import { runDirectCommand } from "../src/direct-command.js";
import type { AuditPort } from "../src/tool-gate.js";

class RecordingAudit implements AuditPort {
  readonly events: Array<{ eventType: string; payload: Record<string, unknown> }> = [];

  async append(eventType: string, payload: Record<string, unknown>): Promise<void> {
    this.events.push({ eventType, payload });
  }
}

class RecordingExecutor {
  readonly calls: Array<{ argv: readonly string[]; spec: SandboxSpec }> = [];

  async execute(argv: readonly string[], spec: SandboxSpec): Promise<SandboxExecutionResult> {
    this.calls.push({ argv, spec });
    return {
      enforced: false,
      runner: "noop",
      exitCode: 0,
      stdout: "ok",
      stderr: "",
      timedOut: false,
      metadata: { profile: spec.profile },
    };
  }
}

describe("runDirectCommand", () => {
  it("executes operator-authored safe commands without LLM planning", async () => {
    const executor = new RecordingExecutor();
    const audit = new RecordingAudit();

    const result = await runDirectCommand({
      command: "uname -a",
      policy: new PolicyEngine([]),
      audit,
      executor,
      sandbox: { profile: "noop", timeoutMs: 1000 },
    });

    expect(result.executed).toBe(true);
    expect(executor.calls[0]?.argv).toEqual(["uname", "-a"]);
    expect(audit.events[0]?.eventType).toBe("policy.allow");
  });

  it("blocks unsafe direct commands before executor invocation", async () => {
    const executor = new RecordingExecutor();
    const audit = new RecordingAudit();

    const result = await runDirectCommand({
      command: "rm -rf /",
      policy: new PolicyEngine([]),
      audit,
      executor,
      sandbox: { profile: "noop", timeoutMs: 1000 },
    });

    expect(result.executed).toBe(false);
    expect(result.modelText).toContain("destructive command targeting root filesystem");
    expect(executor.calls).toHaveLength(0);
    expect(audit.events[0]?.eventType).toBe("policy.block");
  });
});
