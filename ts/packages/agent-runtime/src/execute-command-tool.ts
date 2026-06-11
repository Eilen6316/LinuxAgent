import { redactOutput } from "@linuxagent/executor";
import type { SandboxExecutionResult, SandboxSpec } from "@linuxagent/sandbox";
import type { LinuxAgentToolGate, ToolCallResult } from "./tool-gate.js";

export interface CommandExecutorPort {
  execute(
    argv: readonly string[],
    spec: SandboxSpec,
    signal?: AbortSignal,
  ): Promise<SandboxExecutionResult>;
}

export interface ExecuteCommandToolInput {
  args: unknown;
  sandbox: SandboxSpec;
  gate: Pick<LinuxAgentToolGate, "beforeToolCall">;
  executor: CommandExecutorPort;
  toolCallId?: string;
  signal?: AbortSignal;
  maxModelChars?: number;
}

export type ExecuteCommandToolResult =
  | {
      executed: false;
      blockedReason: string;
      modelText: string;
      redacted: false;
      truncated: false;
    }
  | {
      executed: true;
      exitCode: number | null;
      sandbox: Pick<SandboxExecutionResult, "enforced" | "runner" | "timedOut" | "metadata">;
      modelText: string;
      redacted: boolean;
      truncated: boolean;
    };

export async function executeCommandTool(
  input: ExecuteCommandToolInput,
): Promise<ExecuteCommandToolResult> {
  const gateResult = await input.gate.beforeToolCall(
    {
      args: { ...commandToolArgsRecord(input.args), sandbox: input.sandbox },
      ...(input.toolCallId !== undefined ? { toolCallId: input.toolCallId } : {}),
    },
    input.signal,
  );
  if (gateResult?.block) {
    return blocked(gateResult);
  }
  const argv = commandArgvFromToolArgs(input.args);
  const result = await input.executor.execute(argv, input.sandbox, input.signal);
  const modelOutput = redactOutput(
    formatExecutionResultForModel(argv, result),
    input.maxModelChars,
  );
  return {
    executed: true,
    exitCode: result.exitCode,
    sandbox: {
      enforced: result.enforced,
      runner: result.runner,
      timedOut: result.timedOut,
      metadata: result.metadata,
    },
    modelText: modelOutput.text,
    redacted: modelOutput.redacted,
    truncated: modelOutput.truncated,
  };
}

function blocked(result: ToolCallResult): ExecuteCommandToolResult {
  return {
    executed: false,
    blockedReason: result.reason,
    modelText: `blocked: ${result.reason}`,
    redacted: false,
    truncated: false,
  };
}

function commandArgvFromToolArgs(args: unknown): string[] {
  const record = commandToolArgsRecord(args);
  const argv = record.argv;
  if (!Array.isArray(argv)) throw new Error("command tool args must contain argv");
  return argv.map((value) => String(value));
}

function commandToolArgsRecord(args: unknown): Record<string, unknown> {
  if (!args || typeof args !== "object" || !("argv" in args)) {
    throw new Error("command tool args must contain argv");
  }
  return args as Record<string, unknown>;
}

export function formatExecutionResultForModel(
  argv: readonly string[],
  result: SandboxExecutionResult,
): string {
  return [
    `argv=${JSON.stringify(argv)}`,
    `exit_code=${result.exitCode}`,
    `sandbox.enforced=${result.enforced}`,
    `sandbox.runner=${result.runner}`,
    `stdout=${result.stdout.trimEnd()}`,
    `stderr=${result.stderr.trimEnd()}`,
  ].join("\n");
}
