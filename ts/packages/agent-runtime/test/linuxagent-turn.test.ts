import { describe, expect, it } from "vitest";
import { PolicyEngine } from "../../policy/src/index.js";
import type { SandboxExecutionResult, SandboxSpec } from "../../sandbox/src/index.js";
import type { ApprovalDecision, ApprovalPort, ApprovalRequest } from "../src/approval.js";
import { type IntentRouter, runLinuxAgentTurn } from "../src/linuxagent-turn.js";
import { CommandPlanner, type PlannerModel } from "../src/planner.js";
import type { AuditPort } from "../src/tool-gate.js";

class RecordingAudit implements AuditPort {
  readonly events: Array<{ eventType: string; payload: Record<string, unknown> }> = [];

  async append(eventType: string, payload: Record<string, unknown>): Promise<void> {
    this.events.push({ eventType, payload });
  }
}

class StaticApproval implements ApprovalPort {
  readonly requests: ApprovalRequest[] = [];

  constructor(private readonly decision: ApprovalDecision) {}

  async requestApproval(request: ApprovalRequest): Promise<ApprovalDecision> {
    this.requests.push(request);
    return this.decision;
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
      stdout: "Authorization: Bearer runtime-secret-token",
      stderr: "",
      timedOut: false,
      metadata: { profile: spec.profile },
    };
  }
}

const directRouter: IntentRouter = {
  route: async () => ({ kind: "direct_answer", answer: "Use systemctl status nginx." }),
};

const commandRouter: IntentRouter = {
  route: async () => ({ kind: "command_plan" }),
};

const plannerReturning = (text: string): CommandPlanner =>
  new CommandPlanner({ complete: async () => text } satisfies PlannerModel);

describe("runLinuxAgentTurn", () => {
  it("does not plan or execute direct-answer turns", async () => {
    let plannerCalls = 0;
    const planner = new CommandPlanner({
      complete: async () => {
        plannerCalls += 1;
        return JSON.stringify({ version: 1, summary: "unexpected", steps: [] });
      },
    });
    const executor = new RecordingExecutor();

    const result = await runLinuxAgentTurn({
      input: "what does systemctl do?",
      intentRouter: directRouter,
      planner,
      policy: new PolicyEngine([]),
      approvals: new StaticApproval("approve_once"),
      audit: new RecordingAudit(),
      executor,
      threadId: "t1",
      sandbox: { profile: "noop", timeoutMs: 1000 },
    });

    expect(result).toEqual({ kind: "direct_answer", answer: "Use systemctl status nginx." });
    expect(plannerCalls).toBe(0);
    expect(executor.calls).toHaveLength(0);
  });

  it("blocks unsafe planned commands before executor invocation", async () => {
    const audit = new RecordingAudit();
    const executor = new RecordingExecutor();

    const result = await runLinuxAgentTurn({
      input: "delete everything",
      intentRouter: commandRouter,
      planner: plannerReturning(
        JSON.stringify({
          version: 1,
          summary: "delete root",
          steps: [{ id: "s1", argv: ["rm", "-rf", "/"], source: "llm", reason: "unsafe" }],
        }),
      ),
      policy: new PolicyEngine([]),
      approvals: new StaticApproval("approve_once"),
      audit,
      executor,
      threadId: "t1",
      sandbox: { profile: "noop", timeoutMs: 1000 },
    });

    expect(result.kind).toBe("tool_results");
    if (result.kind !== "tool_results") throw new Error("expected tool results");
    expect(result.results[0]).toMatchObject({ executed: false });
    expect(result.results[0]?.modelText).toContain("destructive command targeting root filesystem");
    expect(executor.calls).toHaveLength(0);
    expect(audit.events[0]?.eventType).toBe("policy.block");
  });

  it("executes approved planned commands and returns redacted analysis text", async () => {
    const approvals = new StaticApproval("approve_once");
    const executor = new RecordingExecutor();

    const result = await runLinuxAgentTurn({
      input: "check kernel",
      intentRouter: commandRouter,
      planner: plannerReturning(
        JSON.stringify({
          version: 1,
          summary: "inspect kernel",
          steps: [{ id: "s1", argv: ["uname", "-a"], source: "llm", reason: "inspect kernel" }],
        }),
      ),
      policy: new PolicyEngine([]),
      approvals,
      audit: new RecordingAudit(),
      executor,
      threadId: "t1",
      sandbox: { profile: "noop", timeoutMs: 1000 },
    });

    expect(executor.calls).toHaveLength(1);
    expect(approvals.requests).toHaveLength(1);
    expect(result.kind).toBe("tool_results");
    if (result.kind !== "tool_results") throw new Error("expected tool results");
    expect(result.results[0]).toMatchObject({ executed: true, redacted: true });
    expect(result.results[0]?.modelText).toContain("[REDACTED]");
    expect(result.results[0]?.modelText).not.toContain("runtime-secret-token");
  });
});
