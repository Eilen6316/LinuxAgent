import { readFileSync } from "node:fs";
import { mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import type {
  ApprovalDecision,
  ApprovalPort,
  ApprovalRequest,
  AuditPort,
  CommandExecutorPort,
  LinuxAgentReactRuntimeInput,
  ReactToolRegistryInput,
  runLinuxAgentReactTurn as runLinuxAgentReactTurnFunction,
  SessionPermissions as SessionPermissionsClass,
} from "@linuxagent/agent-runtime";
import type { PolicyDecision } from "@linuxagent/contracts";
import type { SandboxExecutionResult, SandboxSpec } from "@linuxagent/sandbox";
import { OpenSshManager, type SshProcessTransport } from "@linuxagent/ssh";
import type { ParitySummary } from "./report.js";

type FixtureApprovalDecision = ApprovalDecision | "non_tty";

interface ReactTurnFixture {
  schemaVersion: 1;
  caseId: string;
  userInput: string;
  threadId?: string;
  permissionScope?: { threadId: string; resumedFromThreadId?: string };
  preapprovedCommands?: Array<{ threadId: string; argv: string[] }>;
  modelMessages: ReactTurnModelMessage[];
  policy?: PolicyDecision;
  approval?: FixtureApprovalDecision;
  executor?: {
    exitCode: number | null;
    stdout: string;
    stderr: string;
  };
  filePatch?: {
    approval: "approve" | "deny";
    initialFiles?: Array<{ path: string; content: string }>;
    expectedFiles?: Array<{ path: string; content: string }>;
  };
  ssh?: {
    expectedCalls: number;
  };
  expected: {
    status: "completed" | "blocked" | "pending_approval" | "error";
    assistantMessage?: string;
    approvalRequests: number;
    executorCalls: string[][];
    auditEvents: string[];
    modelTextContains?: string[];
    modelTextNotContains?: string[];
  };
}

type ReactTurnModelMessage =
  | { type: "final"; text: string }
  | { type: "tool_call"; id: string; name: string; args: Record<string, unknown> };

interface ReactAssistantMessage {
  role: "assistant";
  content: Array<
    | { type: "text"; text: string }
    | { type: "toolCall"; id: string; name: string; arguments: Record<string, unknown> }
  >;
  stopReason: "stop" | "toolUse";
}

export async function runReactTurnParity(
  fixturePath = defaultReactTurnFixturePath(),
): Promise<ParitySummary> {
  const fixtures = readReactTurnFixtures(fixturePath);
  const failures: string[] = [];

  for (const fixture of fixtures) {
    failures.push(...(await runFixture(fixture)));
  }

  return {
    suite: "react-turn",
    passed: fixtures.length - new Set(failures.map((failure) => failure.split(":")[0])).size,
    total: fixtures.length,
    failures,
  };
}

export function defaultReactTurnFixturePath(): string {
  return resolve(process.cwd(), "parity/fixtures/react-turns.jsonl");
}

function readReactTurnFixtures(fixturePath: string): ReactTurnFixture[] {
  const content = readFileSync(fixturePath, "utf8").trim();
  if (content.length === 0) return [];
  return content
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line) as ReactTurnFixture);
}

async function runFixture(rawFixture: ReactTurnFixture): Promise<string[]> {
  const { runLinuxAgentReactTurn, SessionPermissions } = await loadAgentRuntimeModule();
  const tmp = await mkdtemp(resolve(tmpdir(), "linuxagent-react-turn-parity-"));
  const fixture = resolveFixture(rawFixture, tmp);
  const audit = new RecordingAudit();
  const approvals = new RecordingApproval(fixture.approval ?? "approve_once");
  const executor = new RecordingExecutor(fixture.executor);
  const permissions = new SessionPermissions();
  const sshTransport = new RecordingSshTransport();
  for (const permission of fixture.preapprovedCommands ?? []) {
    permissions.allow({ threadId: permission.threadId }, permission.argv);
  }
  await setupFiles(fixture.filePatch, tmp);

  const result = await runLinuxAgentReactTurn({
    input: fixture.userInput,
    systemPrompt: "You are LinuxAgent.",
    model: fakeModel(),
    policy: new StaticPolicy(fixture.policy ?? safeDecision()),
    approvals,
    audit,
    executor,
    threadId: fixture.threadId ?? "thread-1",
    ...(fixture.permissionScope !== undefined ? { permissionScope: fixture.permissionScope } : {}),
    permissions,
    sandbox: { profile: "noop", timeoutMs: 1000 },
    streamFn: fakeStream(fixture.modelMessages),
    ...(fixture.filePatch !== undefined ? { filePatch: filePatchPorts(fixture, audit, tmp) } : {}),
    ...(fixture.ssh !== undefined ? { ssh: sshPorts(sshTransport) } : {}),
  });
  const failures = compareFixture(fixture, {
    status: result.status,
    assistantMessage: result.assistantMessage,
    approvalRequests: approvals.requests.length,
    executorCalls: executor.calls.map((call) => [...call.argv]),
    auditEvents: audit.events.map((event) => event.eventType),
    modelText: result.toolResults.map((toolResult) => toolResult.modelText).join("\n"),
    sshCalls: sshTransport.calls.length,
  });
  failures.push(...(await compareExpectedFiles(fixture, tmp)));
  return failures.map((failure) => `${fixture.caseId}: ${failure}`);
}

async function loadAgentRuntimeModule(): Promise<{
  runLinuxAgentReactTurn: typeof runLinuxAgentReactTurnFunction;
  SessionPermissions: typeof SessionPermissionsClass;
}> {
  return (await import(agentRuntimeModuleSpecifier())) as {
    runLinuxAgentReactTurn: typeof runLinuxAgentReactTurnFunction;
    SessionPermissions: typeof SessionPermissionsClass;
  };
}

function agentRuntimeModuleSpecifier(): string {
  if (process.env.VITEST === "true" || import.meta.url.endsWith(".ts")) {
    return "../../packages/agent-runtime/src/index.js";
  }
  return "../../packages/agent-runtime/dist/src/index.js";
}

function compareFixture(
  fixture: ReactTurnFixture,
  actual: {
    status: string;
    assistantMessage: string;
    approvalRequests: number;
    executorCalls: string[][];
    auditEvents: string[];
    modelText: string;
    sshCalls: number;
  },
): string[] {
  const failures: string[] = [];
  if (actual.status !== fixture.expected.status) {
    failures.push(`expected status ${fixture.expected.status}, got ${actual.status}`);
  }
  if (
    fixture.expected.assistantMessage !== undefined &&
    actual.assistantMessage !== fixture.expected.assistantMessage
  ) {
    failures.push(
      `expected assistant ${JSON.stringify(fixture.expected.assistantMessage)}, got ${JSON.stringify(
        actual.assistantMessage,
      )}`,
    );
  }
  if (actual.approvalRequests !== fixture.expected.approvalRequests) {
    failures.push(
      `expected ${fixture.expected.approvalRequests} approval requests, got ${actual.approvalRequests}`,
    );
  }
  if (JSON.stringify(actual.executorCalls) !== JSON.stringify(fixture.expected.executorCalls)) {
    failures.push(
      `expected executor calls ${JSON.stringify(
        fixture.expected.executorCalls,
      )}, got ${JSON.stringify(actual.executorCalls)}`,
    );
  }
  if (JSON.stringify(actual.auditEvents) !== JSON.stringify(fixture.expected.auditEvents)) {
    failures.push(
      `expected audit events ${JSON.stringify(fixture.expected.auditEvents)}, got ${JSON.stringify(
        actual.auditEvents,
      )}`,
    );
  }
  for (const expected of fixture.expected.modelTextContains ?? []) {
    if (!actual.modelText.includes(expected)) {
      failures.push(`expected model observation to contain ${JSON.stringify(expected)}`);
    }
  }
  for (const forbidden of fixture.expected.modelTextNotContains ?? []) {
    if (actual.modelText.includes(forbidden)) {
      failures.push(`expected model observation to omit ${JSON.stringify(forbidden)}`);
    }
  }
  if (fixture.ssh !== undefined && actual.sshCalls !== fixture.ssh.expectedCalls) {
    failures.push(`expected ${fixture.ssh.expectedCalls} ssh calls, got ${actual.sshCalls}`);
  }
  return failures;
}

async function setupFiles(filePatch: ReactTurnFixture["filePatch"], tmp: string): Promise<void> {
  for (const file of filePatch?.initialFiles ?? []) {
    const path = resolvePlaceholders(file.path, tmp);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, resolvePlaceholders(file.content, tmp), "utf8");
  }
}

async function compareExpectedFiles(fixture: ReactTurnFixture, tmp: string): Promise<string[]> {
  const failures: string[] = [];
  for (const file of fixture.filePatch?.expectedFiles ?? []) {
    const path = resolvePlaceholders(file.path, tmp);
    const actual = await readFile(path, "utf8");
    const expected = resolvePlaceholders(file.content, tmp);
    if (actual !== expected) {
      failures.push(
        `expected ${path} content ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
      );
    }
  }
  return failures;
}

function filePatchPorts(
  fixture: ReactTurnFixture,
  audit: RecordingAudit,
  tmp: string,
): NonNullable<ReactToolRegistryInput["filePatch"]> {
  return {
    pathPolicy: { allowedRoots: [resolvePlaceholders("{tmp}/allowed", tmp)] },
    approval: { approvePatch: async () => fixture.filePatch?.approval ?? "deny" },
    audit,
  };
}

function sshPorts(transport: RecordingSshTransport): NonNullable<ReactToolRegistryInput["ssh"]> {
  const manager = new OpenSshManager(transport);
  return {
    execute: (input) => manager.execute(input),
  };
}

function resolveFixture(fixture: ReactTurnFixture, tmp: string): ReactTurnFixture {
  return resolveValue(fixture, tmp) as ReactTurnFixture;
}

function resolveValue(value: unknown, tmp: string): unknown {
  if (typeof value === "string") return resolvePlaceholders(value, tmp);
  if (Array.isArray(value)) return value.map((item) => resolveValue(item, tmp));
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [key, resolveValue(child, tmp)]),
    );
  }
  return value;
}

function resolvePlaceholders(value: string, tmp: string): string {
  return value.replaceAll("{tmp}", tmp);
}

class StaticPolicy {
  readonly calls: string[][] = [];

  constructor(private readonly decision: PolicyDecision) {}

  evaluate(argv: readonly string[]): PolicyDecision {
    this.calls.push([...argv]);
    return this.decision;
  }
}

class RecordingApproval implements ApprovalPort {
  readonly requests: ApprovalRequest[] = [];

  constructor(private readonly decision: FixtureApprovalDecision) {}

  async requestApproval(request: ApprovalRequest): Promise<ApprovalDecision> {
    this.requests.push(request);
    return this.decision === "non_tty" ? "deny" : this.decision;
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

  constructor(private readonly result?: ReactTurnFixture["executor"]) {}

  async execute(argv: readonly string[], spec: SandboxSpec): Promise<SandboxExecutionResult> {
    this.calls.push({ argv, spec });
    return {
      enforced: false,
      runner: "noop",
      exitCode: this.result?.exitCode ?? 0,
      stdout: this.result?.stdout ?? "",
      stderr: this.result?.stderr ?? "",
      timedOut: false,
      metadata: { profile: spec.profile },
    };
  }
}

class RecordingSshTransport implements SshProcessTransport {
  readonly calls: Array<{ argv: readonly string[] }> = [];

  async run(argv: readonly string[]): Promise<{
    exitCode: number | null;
    stdout: string;
    stderr: string;
    timedOut: boolean;
  }> {
    this.calls.push({ argv });
    return { exitCode: 0, stdout: "ok\n", stderr: "", timedOut: false };
  }
}

function fakeStream(messages: readonly ReactTurnModelMessage[]) {
  const assistantMessages = messages.map(assistantMessageFromFixture);
  let index = 0;
  return () => {
    const message = assistantMessages[index];
    if (!message) throw new Error("fake stream exhausted");
    index += 1;
    const events: unknown[] = [{ type: "start" as const, partial: message }];
    for (const [contentIndex, content] of message.content.entries()) {
      if (content.type === "text") {
        events.push({ type: "text_start" as const, contentIndex, partial: message });
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

function assistantMessageFromFixture(message: ReactTurnModelMessage): ReactAssistantMessage {
  if (message.type === "final") {
    return {
      ...baseAssistantMessage(),
      content: [{ type: "text", text: message.text }],
      stopReason: "stop",
    };
  }
  return {
    ...baseAssistantMessage(),
    content: [
      {
        type: "toolCall",
        id: message.id,
        name: message.name,
        arguments: message.args,
      },
    ],
    stopReason: "toolUse",
  };
}

function baseAssistantMessage(): Omit<ReactAssistantMessage, "content" | "stopReason"> {
  return {
    role: "assistant",
  };
}

function fakeModel(): LinuxAgentReactRuntimeInput["model"] {
  return {
    id: "fake-react-turn",
    provider: "fake",
    api: "fake",
    name: "Fake ReAct Turn",
    baseUrl: "http://localhost:0",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 4096,
    maxTokens: 1024,
  };
}

function safeDecision(): PolicyDecision {
  return {
    level: "SAFE",
    reason: null,
    riskScore: 0,
    capabilities: [],
    matchedRules: [],
    neverWhitelist: false,
  };
}
