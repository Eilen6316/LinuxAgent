import type {
  ExecuteCommandToolResult,
  LinuxAgentTurnResult,
} from "../../agent-runtime/src/index.js";
import { routeSlashCommand, type SlashRoute } from "./slash-router.js";

export interface LinuxAgentTuiApp {
  readonly name: "linuxagent-ts";
}

export interface ChatTurnRunner {
  runTurn(input: string, signal?: AbortSignal): Promise<LinuxAgentTurnResult>;
}

export interface DirectCommandRunner {
  runDirectCommand(command: string, signal?: AbortSignal): Promise<ExecuteCommandToolResult>;
}

export type ChatSessionResult =
  | { kind: "runtime"; result: LinuxAgentTurnResult }
  | { kind: "direct_command"; result: ExecuteCommandToolResult }
  | Exclude<SlashRoute, { kind: "not_slash" }>;

export class LinuxAgentChatSession {
  constructor(
    private readonly runner: ChatTurnRunner,
    private readonly directRunner?: DirectCommandRunner,
  ) {}

  async handleInput(input: string, signal?: AbortSignal): Promise<ChatSessionResult> {
    const route = routeSlashCommand(input);
    if (route.kind !== "not_slash") return route;
    if (input.startsWith("!") && this.directRunner) {
      return {
        kind: "direct_command",
        result: await this.directRunner.runDirectCommand(input.slice(1), signal),
      };
    }
    return { kind: "runtime", result: await this.runner.runTurn(input, signal) };
  }
}

export function createLinuxAgentTuiApp(): LinuxAgentTuiApp {
  return { name: "linuxagent-ts" };
}
