import type { PolicyEngine } from "@linuxagent/policy";
import type { SandboxSpec } from "@linuxagent/sandbox";
import type { ApprovalPort } from "../approval.js";
import type { CommandExecutorPort, ExecuteCommandToolResult } from "../execute-command-tool.js";
import { type PermissionScope, SessionPermissions } from "../session-permissions.js";
import { type AuditPort, LinuxAgentToolGate } from "../tool-gate.js";
import {
  PENDING_APPROVAL_REASON,
  type PendingRequest,
  type PendingRequestSink,
  removePendingRequest,
  upsertPendingRequest,
} from "./pending-request.js";
import type { ReactSessionMessageSnapshot, ReactSessionStore } from "./session-store.js";
import { buildReactToolRegistry } from "./tool-registry.js";

interface ReactModel {
  id?: string;
  model?: string;
  provider: string;
  api?: string;
  [key: string]: unknown;
}

interface ReactStream {
  [Symbol.asyncIterator](): AsyncIterator<unknown>;
  result(): Promise<ReactAssistantMessage>;
}

type ReactStreamFn = (...args: unknown[]) => ReactStream | Promise<ReactStream>;

interface ReactAssistantMessage {
  role: "assistant";
  content: Array<{ type: string; text?: string; [key: string]: unknown }>;
}

interface ReactAgentEvent {
  type: string;
  message?: unknown;
  result?: { details?: { result?: ExecuteCommandToolResult } };
}

type ReactAgentConstructor = new (
  options: Record<string, unknown>,
) => {
  subscribe(listener: (event: ReactAgentEvent) => void): () => void;
  prompt(input: string): Promise<void>;
};

interface ReactAfterToolCallContext {
  result: { details?: { result?: ExecuteCommandToolResult } };
}

export interface LinuxAgentReactRuntimeInput {
  input: string;
  systemPrompt: string;
  model: ReactModel;
  policy: Pick<PolicyEngine, "evaluate">;
  approvals: ApprovalPort;
  audit: AuditPort;
  executor: CommandExecutorPort;
  threadId: string;
  sandbox: SandboxSpec;
  permissions?: SessionPermissions;
  permissionScope?: PermissionScope;
  sessionStore?: ReactSessionStore;
  approvalExpiresInMs?: number;
  now?: () => Date;
  streamFn?: ReactStreamFn;
  signal?: AbortSignal;
}

export interface LinuxAgentReactTurnResult {
  status: "completed" | "blocked" | "pending_approval" | "error";
  assistantMessage: string;
  toolResults: ExecuteCommandToolResult[];
  pendingRequest?: PendingRequest;
}

export async function runLinuxAgentReactTurn(
  input: LinuxAgentReactRuntimeInput,
): Promise<LinuxAgentReactTurnResult> {
  const { Agent } = await loadPiAgentCore();
  const now = input.now ?? (() => new Date());
  const sessionThreadId = sessionThreadIdForInput(input);
  const storedSession = await input.sessionStore?.load(sessionThreadId);
  const permissions =
    input.permissions ?? SessionPermissions.fromSnapshot(storedSession?.permissions);
  let messages: ReactSessionMessageSnapshot[] = storedSession?.messages ?? [];
  let pendingRequests: PendingRequest[] = storedSession?.pendingRequests ?? [];
  const saveSession = async () => {
    if (input.sessionStore === undefined) return;
    await input.sessionStore.save({
      threadId: sessionThreadId,
      messages,
      pendingRequests,
      permissions: permissions.snapshot(),
      updatedAt: now().toISOString(),
    });
  };
  const pendingRequestSink = pendingRequestSinkForSession(
    () => pendingRequests,
    (nextPendingRequests) => {
      pendingRequests = nextPendingRequests;
    },
    saveSession,
    input.sessionStore !== undefined,
  );
  const gate = new LinuxAgentToolGate(
    input.policy,
    permissions,
    input.approvals,
    input.audit,
    input.threadId,
    {
      permissionScope: input.permissionScope ?? { threadId: input.threadId },
      ...(pendingRequestSink !== undefined ? { pendingRequests: pendingRequestSink } : {}),
      now,
      ...(input.approvalExpiresInMs !== undefined
        ? { approvalExpiresInMs: input.approvalExpiresInMs }
        : {}),
    },
  );
  const toolResults: ExecuteCommandToolResult[] = [];
  let assistantMessage = "";

  const agent = new Agent({
    initialState: {
      systemPrompt: input.systemPrompt,
      model: input.model,
      tools: buildReactToolRegistry({
        gate,
        executor: input.executor,
        sandbox: input.sandbox,
        ...(input.signal ? { signal: input.signal } : {}),
      }),
    },
    ...(input.streamFn ? { streamFn: input.streamFn } : {}),
    toolExecution: "sequential",
    async afterToolCall(context: ReactAfterToolCallContext) {
      const details = context.result.details;
      if (details?.result === undefined) return undefined;
      const result = details.result;
      return {
        content: [{ type: "text", text: result.modelText }],
        details: { result },
        isError: !result.executed,
        terminate: !result.executed,
      };
    },
  });

  agent.subscribe((event) => {
    collectEvent(event, toolResults, (text) => {
      assistantMessage = text;
    });
  });

  await agent.prompt(input.input);
  messages = messagesForCompletedTurn(messages, input.input, assistantMessage);
  await saveSession();

  const status = statusFromResults(toolResults);
  const pendingRequest = pendingRequests.at(-1);
  return {
    status,
    assistantMessage,
    toolResults,
    ...(status === "pending_approval" && pendingRequest !== undefined ? { pendingRequest } : {}),
  };
}

function pendingRequestSinkForSession(
  current: () => PendingRequest[],
  setPendingRequests: (requests: PendingRequest[]) => void,
  saveSession: () => Promise<void>,
  enabled: boolean,
): PendingRequestSink | undefined {
  if (!enabled) return undefined;
  return {
    async open(request) {
      setPendingRequests(upsertPendingRequest(current(), request));
      await saveSession();
    },
    async resolve(threadId, requestId) {
      setPendingRequests(removePendingRequest(current(), threadId, requestId));
      await saveSession();
    },
  };
}

function collectEvent(
  event: ReactAgentEvent,
  toolResults: ExecuteCommandToolResult[],
  setAssistantMessage: (text: string) => void,
): void {
  if (event.type === "tool_execution_end") {
    const details = event.result?.details;
    if (details?.result !== undefined) {
      toolResults.push(details.result);
    }
    return;
  }
  if (event.type !== "message_end" || !isReactAssistantMessage(event.message)) return;
  const text = event.message.content
    .filter((content) => content.type === "text")
    .map((content) => content.text ?? "")
    .join("");
  if (text.length > 0) setAssistantMessage(text);
}

function statusFromResults(
  results: readonly ExecuteCommandToolResult[],
): LinuxAgentReactTurnResult["status"] {
  if (
    results.some((result) => !result.executed && result.blockedReason === PENDING_APPROVAL_REASON)
  ) {
    return "pending_approval";
  }
  if (results.some((result) => !result.executed)) return "blocked";
  return "completed";
}

function sessionThreadIdForInput(input: LinuxAgentReactRuntimeInput): string {
  return (
    input.permissionScope?.resumedFromThreadId ?? input.permissionScope?.threadId ?? input.threadId
  );
}

function messagesForCompletedTurn(
  messages: readonly ReactSessionMessageSnapshot[],
  userInput: string,
  assistantMessage: string,
): ReactSessionMessageSnapshot[] {
  const next: ReactSessionMessageSnapshot[] = [...messages, { role: "user", text: userInput }];
  if (assistantMessage.length > 0) next.push({ role: "assistant", text: assistantMessage });
  return next;
}

function isReactAssistantMessage(message: unknown): message is ReactAssistantMessage {
  return (
    typeof message === "object" &&
    message !== null &&
    "role" in message &&
    (message as { role: unknown }).role === "assistant" &&
    "content" in message &&
    Array.isArray((message as { content: unknown }).content)
  );
}

async function loadPiAgentCore(): Promise<{ Agent: ReactAgentConstructor }> {
  const specifier: string = "@earendil-works/pi-agent-core";
  return (await import(specifier)) as {
    Agent: ReactAgentConstructor;
  };
}
