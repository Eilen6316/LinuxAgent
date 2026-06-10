import { describe, expect, it } from "vitest";
import type { PolicyDecision } from "../../../contracts/src/index.js";
import type { SandboxExecutionResult, SandboxSpec } from "../../../sandbox/src/index.js";
import type { ApprovalPort } from "../../src/approval.js";
import type { CommandExecutorPort } from "../../src/execute-command-tool.js";
import { type LinuxAgentReactRuntimeInput, runLinuxAgentReactTurn } from "../../src/react/index.js";
import type { AuditPort } from "../../src/tool-gate.js";

class StaticPolicy {
  readonly calls: string[][] = [];

  constructor(private readonly decision: PolicyDecision) {}

  evaluate(argv: readonly string[]): PolicyDecision {
    this.calls.push([...argv]);
    return this.decision;
  }
}

class StaticApproval implements ApprovalPort {
  readonly requests: Parameters<ApprovalPort["requestApproval"]>[0][] = [];

  constructor(private readonly decision: "approve_once" | "approve_thread" | "deny") {}

  async requestApproval(
    request: Parameters<ApprovalPort["requestApproval"]>[0],
  ): Promise<"approve_once" | "approve_thread" | "deny"> {
    this.requests.push(request);
    return this.decision;
  }
}

class RecordingAudit implements AuditPort {
  readonly events: Array<{ eventType: string; payload: Record<string, unknown> }> = [];

  async append(eventType: string, payload: Record<string, unknown>): Promise<void> {
    this.events.push({ eventType, payload });
  }
}

class RecordingExecutor implements CommandExecutorPort {
  readonly calls: Array<{ argv: readonly string[]; spec: SandboxSpec }> = [];

  async execute(argv: readonly string[], spec: SandboxSpec): Promise<SandboxExecutionResult> {
    this.calls.push({ argv, spec });
    return {
      enforced: false,
      runner: "noop",
      exitCode: 0,
      stdout: "kernel ok\nAuthorization: Bearer secret-token-value\n",
      stderr: "",
      timedOut: false,
      metadata: { profile: spec.profile },
    };
  }
}

describe("runLinuxAgentReactTurn", () => {
  it("runs one pi-agent-core command turn through LinuxAgentToolGate", async () => {
    const policy = new StaticPolicy(decision("CONFIRM", false));
    const approvals = new StaticApproval("approve_once");
    const audit = new RecordingAudit();
    const executor = new RecordingExecutor();

    const result = await runLinuxAgentReactTurn(
      input({
        policy,
        approvals,
        audit,
        executor,
        streamFn: fakeStream([commandMessage(["uname", "-a"]), finalMessage("checked kernel")]),
      }),
    );

    expect(result.status).toBe("completed");
    expect(result.assistantMessage).toBe("checked kernel");
    expect(policy.calls).toEqual([[..."uname -a".split(" ")]]);
    expect(approvals.requests).toHaveLength(1);
    expect(executor.calls).toEqual([
      { argv: ["uname", "-a"], spec: { profile: "noop", timeoutMs: 1000 } },
    ]);
    expect(audit.events.map((event) => event.eventType)).toContain("hitl.decision");
    expect(result.toolResults).toHaveLength(1);
    expect(result.toolResults[0]?.modelText).not.toContain("secret-token-value");
    expect(result.toolResults[0]?.modelText).toContain("[REDACTED]");
  });

  it("returns a blocked observation when approval denies the command", async () => {
    const policy = new StaticPolicy(decision("CONFIRM", false));
    const approvals = new StaticApproval("deny");
    const audit = new RecordingAudit();
    const executor = new RecordingExecutor();

    const result = await runLinuxAgentReactTurn(
      input({
        policy,
        approvals,
        audit,
        executor,
        streamFn: fakeStream([
          commandMessage(["uname", "-a"]),
          finalMessage("cannot run without approval"),
        ]),
      }),
    );

    expect(result.status).toBe("blocked");
    expect(executor.calls).toHaveLength(0);
    expect(result.toolResults).toEqual([
      {
        executed: false,
        blockedReason: "operator denied command",
        modelText: "blocked: operator denied command",
        redacted: false,
        truncated: false,
      },
    ]);
    expect(audit.events.map((event) => event.eventType)).toContain("hitl.decision");
  });
});

function input(overrides: {
  policy: LinuxAgentReactRuntimeInput["policy"];
  approvals: ApprovalPort;
  audit: AuditPort;
  executor: CommandExecutorPort;
  streamFn: NonNullable<LinuxAgentReactRuntimeInput["streamFn"]>;
}): LinuxAgentReactRuntimeInput {
  return {
    input: "check kernel",
    systemPrompt: "You are LinuxAgent.",
    model: {
      id: "fake-react",
      provider: "fake",
      api: "fake",
      name: "Fake ReAct",
      baseUrl: "http://localhost:0",
      reasoning: false,
      input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
      contextWindow: 4096,
      maxTokens: 1024,
    },
    threadId: "thread-1",
    sandbox: { profile: "noop", timeoutMs: 1000 },
    ...overrides,
  };
}

function commandMessage(argv: string[]) {
  return assistantMessage(
    [
      {
        type: "toolCall",
        id: "call-1",
        name: "linuxagent_execute_command",
        arguments: { argv },
      },
    ],
    "toolUse",
  );
}

function finalMessage(text: string) {
  return assistantMessage([{ type: "text", text }], "stop");
}

function assistantMessage(
  content: Array<
    | { type: "text"; text: string }
    | { type: "toolCall"; id: string; name: string; arguments: Record<string, unknown> }
  >,
  stopReason: "stop" | "toolUse",
) {
  return {
    role: "assistant" as const,
    api: "fake",
    provider: "fake",
    model: "fake-react",
    usage: {
      input: 0,
      output: 0,
      cacheRead: 0,
      cacheWrite: 0,
      totalTokens: 0,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
    },
    content,
    stopReason,
    timestamp: Date.now(),
  };
}

function fakeStream(messages: ReturnType<typeof assistantMessage>[]) {
  let index = 0;
  return () => {
    const message = messages[index];
    if (!message) throw new Error("fake stream exhausted");
    index += 1;
    const events: unknown[] = [{ type: "start" as const, partial: message }];
    for (const [contentIndex, content] of message.content.entries()) {
      if (content.type === "text") {
        events.push({
          type: "text_start" as const,
          contentIndex,
          partial: message,
        });
        events.push({
          type: "text_delta" as const,
          contentIndex,
          delta: content.text,
          partial: message,
        });
        events.push({
          type: "text_end" as const,
          contentIndex,
          content: content.text,
          partial: message,
        });
      } else {
        events.push({
          type: "toolcall_end" as const,
          contentIndex,
          toolCall: content,
          partial: message,
        });
      }
    }
    events.push({ type: "done" as const, reason: message.stopReason, message });
    return {
      async *[Symbol.asyncIterator]() {
        for (const event of events) {
          yield event;
        }
      },
      async result() {
        return message;
      },
    };
  };
}

function decision(level: "SAFE" | "CONFIRM" | "BLOCK", neverWhitelist: boolean): PolicyDecision {
  return {
    level,
    reason: level === "BLOCK" ? "blocked" : "confirm",
    riskScore: level === "BLOCK" ? 100 : 60,
    capabilities: [],
    matchedRules: [],
    neverWhitelist,
  };
}
