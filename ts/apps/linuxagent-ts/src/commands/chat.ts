import type { LinuxAgentTurnResult } from "@linuxagent/agent-runtime";
import { type ChatSessionResult, LinuxAgentChatSession } from "@linuxagent/tui";

export async function runChatCommand(input?: string): Promise<string> {
  if (input === undefined) return "linuxagent-ts chat";
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
