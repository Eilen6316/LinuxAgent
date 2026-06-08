import { redactOutput } from "../../executor/src/index.js";
import type { PolicyEngine } from "../../policy/src/index.js";
import type { SandboxSpec } from "../../sandbox/src/index.js";
import type { CommandExecutorPort, ExecuteCommandToolResult } from "./execute-command-tool.js";
import { formatExecutionResultForModel } from "./execute-command-tool.js";
import type { AuditPort } from "./tool-gate.js";

export interface DirectCommandInput {
  command: string;
  policy: Pick<PolicyEngine, "evaluate">;
  audit: AuditPort;
  executor: CommandExecutorPort;
  sandbox: SandboxSpec;
  signal?: AbortSignal;
}

export async function runDirectCommand(
  input: DirectCommandInput,
): Promise<ExecuteCommandToolResult> {
  const argv = parseDirectCommand(input.command);
  const decision = input.policy.evaluate(argv, { source: "operator" });

  if (decision.level === "BLOCK") {
    await input.audit.append("policy.block", { argv, decision });
    return {
      executed: false,
      blockedReason: decision.reason ?? "blocked by policy",
      modelText: `blocked: ${decision.reason ?? "blocked by policy"}`,
      redacted: false,
      truncated: false,
    };
  }

  await input.audit.append("policy.allow", { argv, decision });
  const result = await input.executor.execute(argv, input.sandbox, input.signal);
  const modelOutput = redactOutput(formatExecutionResultForModel(argv, result));
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

export function parseDirectCommand(command: string): string[] {
  const argv: string[] = [];
  let current = "";
  let quote: "'" | '"' | undefined;

  for (let index = 0; index < command.length; index += 1) {
    const char = command[index];
    if (char === undefined) continue;
    if (quote) {
      if (char === quote) {
        quote = undefined;
      } else {
        current += char;
      }
      continue;
    }
    if (char === "'" || char === '"') {
      quote = char;
      continue;
    }
    if (/\s/.test(char)) {
      if (current.length > 0) {
        argv.push(current);
        current = "";
      }
      continue;
    }
    current += char;
  }

  if (quote) throw new Error("direct command contains an unterminated quote");
  if (current.length > 0) argv.push(current);
  if (argv.length === 0) throw new Error("direct command must not be empty");
  return argv;
}
