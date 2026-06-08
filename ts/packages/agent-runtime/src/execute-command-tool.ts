import { redactOutput } from "../../executor/src/index.js";
import type { SandboxExecutionResult, SandboxSpec } from "../../sandbox/src/index.js";
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
  const gateResult = await input.gate.beforeToolCall({ args: input.args }, input.signal);
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
  if (!args || typeof args !== "object" || !("argv" in args)) {
    throw new Error("command tool args must contain argv");
  }
  const argv = (args as { argv: unknown }).argv;
  if (!Array.isArray(argv)) throw new Error("command tool args must contain argv");
  return argv.map((value) => String(value));
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
