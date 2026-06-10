import type { LinuxAgentTurnResult } from "@linuxagent/agent-runtime";
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
}

export async function runChatCommand(
  input?: string,
  options: RunChatCommandOptions = {},
): Promise<string> {
  if (input === undefined) return runInteractiveOrFailClosed(options);
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
