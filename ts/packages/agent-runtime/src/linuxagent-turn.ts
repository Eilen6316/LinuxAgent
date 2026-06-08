import type { PolicyEngine } from "../../policy/src/index.js";
import type { SandboxProfile, SandboxSpec } from "../../sandbox/src/index.js";
import type { ApprovalPort } from "./approval.js";
import type { CommandExecutorPort } from "./execute-command-tool.js";
import { type ExecuteCommandToolResult, executeCommandTool } from "./execute-command-tool.js";
import type { CommandPlanner } from "./planner.js";
import { SessionPermissions } from "./session-permissions.js";
import { type AuditPort, LinuxAgentToolGate } from "./tool-gate.js";

export type IntentDecision =
  | { kind: "direct_answer"; answer: string }
  | { kind: "command_plan" }
  | { kind: "clarify"; question: string };

export interface IntentRouter {
  route(input: string, signal?: AbortSignal): Promise<IntentDecision>;
}

export interface LinuxAgentTurnInput {
  input: string;
  intentRouter: IntentRouter;
  planner: CommandPlanner;
  policy: Pick<PolicyEngine, "evaluate">;
  approvals: ApprovalPort;
  audit: AuditPort;
  executor: CommandExecutorPort;
  threadId: string;
  sandbox: SandboxSpec;
  permissions?: SessionPermissions;
  signal?: AbortSignal;
}

export type LinuxAgentTurnResult =
  | { kind: "direct_answer"; answer: string }
  | { kind: "clarify"; question: string }
  | { kind: "planner_error"; error: "invalid_json" | "schema_invalid"; detail: string }
  | { kind: "tool_results"; results: ExecuteCommandToolResult[] };

export async function runLinuxAgentTurn(input: LinuxAgentTurnInput): Promise<LinuxAgentTurnResult> {
  const intent = await input.intentRouter.route(input.input, input.signal);
  if (intent.kind === "direct_answer") {
    return { kind: "direct_answer", answer: intent.answer };
  }
  if (intent.kind === "clarify") {
    return { kind: "clarify", question: intent.question };
  }

  const plannerResult = await input.planner.plan(input.input, input.signal);
  if (!plannerResult.ok) {
    return { kind: "planner_error", error: plannerResult.error, detail: plannerResult.detail };
  }

  const gate = new LinuxAgentToolGate(
    input.policy,
    input.permissions ?? new SessionPermissions(),
    input.approvals,
    input.audit,
    input.threadId,
  );

  const results: ExecuteCommandToolResult[] = [];
  for (const step of plannerResult.plan.steps) {
    results.push(
      await executeCommandTool({
        args: { argv: step.argv },
        sandbox: {
          ...input.sandbox,
          profile: sandboxProfileOrDefault(step.sandboxProfile, input.sandbox.profile),
        },
        gate,
        executor: input.executor,
        ...(input.signal ? { signal: input.signal } : {}),
      }),
    );
  }
  return { kind: "tool_results", results };
}

function sandboxProfileOrDefault(
  requested: string | undefined,
  fallback: SandboxProfile,
): SandboxProfile {
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
