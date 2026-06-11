import {
  type LinuxAgentReactTurnResult,
  type LinuxAgentTurnResult,
  runLinuxAgentReactTurn,
} from "@linuxagent/agent-runtime";
import {
  type ChatSessionResult,
  createLinuxAgentTuiApp,
  LinuxAgentChatSession,
} from "@linuxagent/tui";

export interface ChatTtyPort {
  isTTY?: boolean;
}

export interface RunChatCommandOptions {
  stdin?: ChatTtyPort;
  stdout?: ChatTtyPort;
  launchInteractive?: () => Promise<string>;
  runReactTurn?: (input: string, signal?: AbortSignal) => Promise<LinuxAgentReactTurnResult>;
  signal?: AbortSignal;
}

export async function runChatCommand(
  input?: string,
  options: RunChatCommandOptions = {},
): Promise<string> {
  if (input === undefined) return runInteractiveOrFailClosed(options);
  if (!isLegacyChatInput(input)) {
    return formatReactTurnResult(
      await (options.runReactTurn ?? runDefaultReactTurn)(input, options.signal),
    );
  }
  return formatChatSessionResult(await createDefaultChatSession().handleInput(input));
}

function createDefaultChatSession(): LinuxAgentChatSession {
  return new LinuxAgentChatSession({
    runTurn: async () => ({
      kind: "direct_answer",
      answer: "experimental chat runtime is not connected to a provider",
    }),
  });
}

export function formatChatSessionResult(result: ChatSessionResult): string {
  switch (result.kind) {
    case "runtime":
      return `linuxagent-ts chat: ${formatRuntimeKind(result.result)}`;
    case "direct_command":
      return `linuxagent-ts chat: direct_command ${result.result.executed ? "executed" : "blocked"}`;
    case "new":
    case "resume":
    case "tools":
    case "quit":
      return `linuxagent-ts chat: ${result.kind}`;
    case "unknown":
      return `linuxagent-ts chat: unknown (${result.usage})`;
  }
}

function formatRuntimeKind(result: LinuxAgentTurnResult): string {
  switch (result.kind) {
    case "direct_answer":
      return "direct_answer";
    case "clarify":
      return "clarify";
    case "planner_error":
      return `planner_error ${result.error}`;
    case "tool_results":
      return `tool_results ${result.results.length}`;
  }
}

async function runInteractiveOrFailClosed(options: RunChatCommandOptions): Promise<string> {
  if (!isInteractiveTty(options)) {
    return "linuxagent-ts chat: non_interactive requires --input";
  }
  return (options.launchInteractive ?? runExperimentalInteractiveChat)();
}

function isInteractiveTty(options: RunChatCommandOptions): boolean {
  const stdinIsTty = options.stdin?.isTTY ?? process.stdin.isTTY ?? false;
  const stdoutIsTty = options.stdout?.isTTY ?? process.stdout.isTTY ?? false;
  return stdinIsTty && stdoutIsTty;
}

async function runExperimentalInteractiveChat(): Promise<string> {
  createLinuxAgentTuiApp();
  return "linuxagent-ts chat: interactive experimental";
}

function isLegacyChatInput(input: string): boolean {
  return input.trimStart().startsWith("/") || input.startsWith("!");
}

function formatReactTurnResult(result: LinuxAgentReactTurnResult): string {
  return `linuxagent-ts chat: react ${result.status}`;
}

async function runDefaultReactTurn(
  input: string,
  signal?: AbortSignal,
): Promise<LinuxAgentReactTurnResult> {
  return await runLinuxAgentReactTurn({
    input,
    systemPrompt: "You are LinuxAgent.",
    model: fakeModel(),
    policy: { evaluate: () => safeDecision() },
    approvals: { requestApproval: async () => "deny" },
    audit: { append: async () => undefined },
    executor: {
      execute: async () => {
        throw new Error("default chat command executor is not configured");
      },
    },
    threadId: "cli-default",
    sandbox: { profile: "noop", timeoutMs: 1000 },
    streamFn: fakeDirectAnswerStream(input),
    ...(signal ? { signal } : {}),
  });
}

function fakeModel() {
  return {
    id: "fake-cli-react",
    provider: "fake",
    api: "fake",
    name: "Fake CLI ReAct",
    baseUrl: "http://localhost:0",
    reasoning: false,
    input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 4096,
    maxTokens: 1024,
  };
}

function safeDecision() {
  return {
    level: "SAFE" as const,
    reason: null,
    riskScore: 0,
    capabilities: [],
    matchedRules: [],
    neverWhitelist: false,
  };
}

function fakeDirectAnswerStream(input: string) {
  return () => {
    const message = {
      role: "assistant" as const,
      content: [{ type: "text", text: `ReAct fake response: ${input}` }],
      stopReason: "stop" as const,
    };
    return {
      async *[Symbol.asyncIterator]() {
        yield { type: "start", partial: message };
        yield { type: "text_start", contentIndex: 0, partial: message };
        yield {
          type: "text_delta",
          contentIndex: 0,
          delta: message.content[0]?.text,
          partial: message,
        };
        yield {
          type: "text_end",
          contentIndex: 0,
          content: message.content[0]?.text,
          partial: message,
        };
        yield { type: "done", reason: message.stopReason, message };
      },
      async result() {
        return message;
      },
    };
  };
}
