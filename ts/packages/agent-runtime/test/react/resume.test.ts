import { mkdtemp, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { PolicyDecision } from "../../../contracts/src/index.js";
import type { SandboxExecutionResult, SandboxSpec } from "../../../sandbox/src/index.js";
import type { ApprovalDecision, ApprovalPort } from "../../src/approval.js";
import type { CommandExecutorPort } from "../../src/execute-command-tool.js";
import {
  createCommandPendingRequest,
  JsonReactSessionStore,
  type LinuxAgentReactRuntimeInput,
  resumeReactSession,
  runLinuxAgentReactTurn,
} from "../../src/react/index.js";
import type { AuditPort } from "../../src/tool-gate.js";

class StaticPolicy {
  readonly calls: string[][] = [];

  constructor(private readonly decision: PolicyDecision) {}

  evaluate(argv: readonly string[]): PolicyDecision {
    this.calls.push([...argv]);
    return this.decision;
  }
}

class RecordingApproval implements ApprovalPort {
  readonly requests: Parameters<ApprovalPort["requestApproval"]>[0][] = [];

  constructor(private readonly decision: ApprovalDecision) {}

  async requestApproval(
    request: Parameters<ApprovalPort["requestApproval"]>[0],
  ): Promise<ApprovalDecision> {
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
      stdout: "ok\n",
      stderr: "",
      timedOut: false,
      metadata: { profile: spec.profile },
    };
  }
}

describe("ReAct resume/session model", () => {
  it("persists pending command requests and reopens them by thread id", async () => {
    const store = new JsonReactSessionStore(await statePath());
    const pending = createCommandPendingRequest({
      threadId: "thread-1",
      requestId: "request-1",
      toolCallId: "call-1",
      auditId: "audit-1",
      argv: ["uname", "-a"],
      reason: "confirm",
      neverWhitelist: false,
      createdAt: "2026-06-10T00:00:00.000Z",
      expiresAt: "2026-06-10T01:00:00.000Z",
    });

    await store.save({
      threadId: "thread-1",
      messages: [{ role: "user", text: "Authorization: Bearer secret-token-value" }],
      pendingRequests: [pending],
      permissions: { scopes: [] },
      updatedAt: "2026-06-10T00:00:00.000Z",
    });

    const resumed = await resumeReactSession({
      store,
      threadId: "thread-1",
      now: new Date("2026-06-10T00:05:00.000Z"),
    });

    expect(resumed.pendingRequest).toMatchObject({
      kind: "command_confirmation",
      threadId: "thread-1",
      requestId: "request-1",
      toolCallId: "call-1",
      auditId: "audit-1",
      argv: ["uname", "-a"],
    });
    expect(resumed.messages[0]?.text).toContain("[REDACTED]");
    expect((await stat(store.path)).mode & 0o777).toBe(0o600);
  });

  it("reuses approve_thread permission only for the same resumed thread", async () => {
    const store = new JsonReactSessionStore(await statePath());
    const firstApproval = new RecordingApproval("approve_thread");

    await runLinuxAgentReactTurn(
      input({
        approvals: firstApproval,
        sessionStore: store,
        streamFn: fakeStream([commandMessage(["uname", "-a"]), finalMessage("checked")]),
      }),
    );

    expect(firstApproval.requests).toHaveLength(1);

    const resumedApproval = new RecordingApproval("deny");
    const resumedExecutor = new RecordingExecutor();
    const resumed = await runLinuxAgentReactTurn(
      input({
        approvals: resumedApproval,
        executor: resumedExecutor,
        threadId: "resume-thread",
        permissionScope: { threadId: "resume-thread", resumedFromThreadId: "thread-1" },
        sessionStore: store,
        streamFn: fakeStream([commandMessage(["uname", "-a"]), finalMessage("checked again")]),
      }),
    );

    expect(resumed.status).toBe("completed");
    expect(resumedApproval.requests).toHaveLength(0);
    expect(resumedExecutor.calls).toHaveLength(1);

    const newThreadApproval = new RecordingApproval("deny");
    const newThreadExecutor = new RecordingExecutor();
    const newThread = await runLinuxAgentReactTurn(
      input({
        approvals: newThreadApproval,
        executor: newThreadExecutor,
        threadId: "new-thread",
        sessionStore: store,
        streamFn: fakeStream([commandMessage(["uname", "-a"]), finalMessage("blocked")]),
      }),
    );

    expect(newThread.status).toBe("blocked");
    expect(newThreadApproval.requests).toHaveLength(1);
    expect(newThreadExecutor.calls).toHaveLength(0);
  });

  it("does not reuse destructive command approval after resume", async () => {
    const store = new JsonReactSessionStore(await statePath());
    const firstApproval = new RecordingApproval("approve_thread");

    await runLinuxAgentReactTurn(
      input({
        approvals: firstApproval,
        policy: new StaticPolicy(decision("CONFIRM", true)),
        sessionStore: store,
        streamFn: fakeStream([
          commandMessage(["systemctl", "stop", "nginx"]),
          finalMessage("stopped"),
        ]),
      }),
    );

    const resumedApproval = new RecordingApproval("deny");
    const resumedExecutor = new RecordingExecutor();
    const result = await runLinuxAgentReactTurn(
      input({
        approvals: resumedApproval,
        executor: resumedExecutor,
        policy: new StaticPolicy(decision("CONFIRM", true)),
        threadId: "resume-thread",
        permissionScope: { threadId: "resume-thread", resumedFromThreadId: "thread-1" },
        sessionStore: store,
        streamFn: fakeStream([
          commandMessage(["systemctl", "stop", "nginx"]),
          finalMessage("blocked"),
        ]),
      }),
    );

    expect(result.status).toBe("blocked");
    expect(resumedApproval.requests).toHaveLength(1);
    expect(resumedExecutor.calls).toHaveLength(0);
  });

  it("stores a pending approval without executing the command", async () => {
    const store = new JsonReactSessionStore(await statePath());
    const audit = new RecordingAudit();
    const executor = new RecordingExecutor();

    const result = await runLinuxAgentReactTurn(
      input({
        approvals: new RecordingApproval("pending"),
        audit,
        executor,
        sessionStore: store,
        streamFn: fakeStream([commandMessage(["uname", "-a"]), finalMessage("waiting")]),
      }),
    );

    const resumed = await resumeReactSession({ store, threadId: "thread-1" });

    expect(result.status).toBe("pending_approval");
    expect(executor.calls).toHaveLength(0);
    expect(audit.events.map((event) => event.eventType)).toContain("hitl.pending");
    expect(resumed.pendingRequest).toMatchObject({
      kind: "command_confirmation",
      threadId: "thread-1",
      argv: ["uname", "-a"],
    });
  });
});

async function statePath(): Promise<string> {
  const dir = await mkdtemp(join(tmpdir(), "linuxagent-react-session-"));
  return join(dir, "sessions.json");
}

function input(
  overrides: Partial<LinuxAgentReactRuntimeInput> & {
    approvals: ApprovalPort;
    streamFn: NonNullable<LinuxAgentReactRuntimeInput["streamFn"]>;
  },
): LinuxAgentReactRuntimeInput {
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
    policy: new StaticPolicy(decision("CONFIRM", false)),
    audit: new RecordingAudit(),
    executor: new RecordingExecutor(),
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
