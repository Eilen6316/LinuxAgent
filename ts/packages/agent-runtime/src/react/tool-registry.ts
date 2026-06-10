import type { SandboxSpec } from "@linuxagent/sandbox";
import type { Static } from "typebox";
import { Type } from "typebox";
import {
  type CommandExecutorPort,
  type ExecuteCommandToolResult,
  executeCommandTool,
} from "../execute-command-tool.js";
import type { LinuxAgentToolGate } from "../tool-gate.js";

export const ExecuteCommandParameters = Type.Object({
  argv: Type.Array(Type.String(), { minItems: 1 }),
  reason: Type.Optional(Type.String()),
  sandboxProfile: Type.Optional(Type.String()),
});

export type ExecuteCommandParameters = Static<typeof ExecuteCommandParameters>;

export interface ReactToolRegistryInput {
  gate: Pick<LinuxAgentToolGate, "beforeToolCall">;
  executor: CommandExecutorPort;
  sandbox: SandboxSpec;
  signal?: AbortSignal;
}

export interface LinuxAgentCommandToolDetails {
  result: ExecuteCommandToolResult;
}

interface ReactAgentTool<TParameters = unknown, TDetails = unknown> {
  name: string;
  label: string;
  description: string;
  parameters: TParameters;
  executionMode: "sequential";
  execute(
    toolCallId: string,
    params: ExecuteCommandParameters,
    signal?: AbortSignal,
  ): Promise<{
    content: Array<{ type: "text"; text: string }>;
    details: TDetails;
    terminate?: boolean;
  }>;
}

export function buildReactToolRegistry(input: ReactToolRegistryInput): ReactAgentTool[] {
  return [createExecuteCommandTool(input)];
}

export function createExecuteCommandTool(
  input: ReactToolRegistryInput,
): ReactAgentTool<typeof ExecuteCommandParameters, LinuxAgentCommandToolDetails> {
  return {
    name: "linuxagent_execute_command",
    label: "Execute command",
    description:
      "Execute an argv-based Linux command through LinuxAgent policy, HITL, audit, and sandbox gates.",
    parameters: ExecuteCommandParameters,
    executionMode: "sequential",
    async execute(_toolCallId, params, signal) {
      const toolInput = {
        args: params,
        sandbox: {
          ...input.sandbox,
          profile: sandboxProfileOrDefault(params.sandboxProfile, input.sandbox.profile),
        },
        gate: input.gate,
        executor: input.executor,
        ...((signal ?? input.signal) ? { signal: signal ?? input.signal } : {}),
      };
      const result = await executeCommandTool(toolInput);
      return {
        content: [{ type: "text", text: result.modelText }],
        details: { result },
        terminate: !result.executed,
      };
    },
  };
}

function sandboxProfileOrDefault(
  requested: string | undefined,
  fallback: SandboxSpec["profile"],
): SandboxSpec["profile"] {
  if (requested === undefined) return fallback;
  if (
    requested === "noop" ||
    requested === "read_only" ||
    requested === "workspace_write" ||
    requested === "system_inspect" ||
    requested === "privileged_passthrough"
  ) {
    return requested;
  }
  throw new Error(`unknown sandbox profile: ${requested}`);
}
