import type { LinuxAgentTurnResult } from "../../agent-runtime/src/index.js";
import { routeSlashCommand, type SlashRoute } from "./slash-router.js";

export interface LinuxAgentTuiApp {
  readonly name: "linuxagent-ts";
}

export interface ChatTurnRunner {
  runTurn(input: string, signal?: AbortSignal): Promise<LinuxAgentTurnResult>;
}

export type ChatSessionResult =
  | { kind: "runtime"; result: LinuxAgentTurnResult }
  | Exclude<SlashRoute, { kind: "not_slash" }>;

export class LinuxAgentChatSession {
  constructor(private readonly runner: ChatTurnRunner) {}

  async handleInput(input: string, signal?: AbortSignal): Promise<ChatSessionResult> {
    const route = routeSlashCommand(input);
    if (route.kind !== "not_slash") return route;
    return { kind: "runtime", result: await this.runner.runTurn(input, signal) };
  }
}

export function createLinuxAgentTuiApp(): LinuxAgentTuiApp {
  return { name: "linuxagent-ts" };
}
