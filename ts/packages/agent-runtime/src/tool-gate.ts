import type { PolicyDecision } from "../../contracts/src/index.js";
import type { PolicyEngine } from "../../policy/src/index.js";
import {
  type ApprovalPort,
  createApprovalRequest,
  normalizeRemoteApprovalMetadata,
} from "./approval.js";
import type { SessionPermissions } from "./session-permissions.js";

export interface ToolCallContext {
  args: unknown;
}

export interface ToolCallResult {
  block: true;
  reason: string;
}

export interface AuditPort {
  append(eventType: string, payload: Record<string, unknown>): Promise<void>;
}

export class LinuxAgentToolGate {
  constructor(
    private readonly policy: Pick<PolicyEngine, "evaluate">,
    private readonly permissions: SessionPermissions,
    private readonly approvals: ApprovalPort,
    private readonly audit: AuditPort,
    private readonly threadId: string,
  ) {}

  async beforeToolCall(
    context: ToolCallContext,
    signal?: AbortSignal,
  ): Promise<ToolCallResult | undefined> {
    const argv = commandArgvFromToolArgs(context.args);
    const remote = remoteMetadataFromToolArgs(context.args);
    const decision = this.policy.evaluate(argv, { source: "llm" }) as PolicyDecision;

    if (decision.level === "BLOCK") {
      await this.audit.append("policy.block", auditPayload(argv, decision, remote));
      return { block: true, reason: decision.reason ?? "blocked by policy" };
    }

    if (decision.level === "SAFE" || this.isAlreadyAllowed(decision, argv)) {
      await this.audit.append("policy.allow", auditPayload(argv, decision, remote));
      return undefined;
    }

    const approval = await this.approvals.requestApproval(
      createApprovalRequest({
        argv,
        reason: decision.reason,
        neverWhitelist: decision.neverWhitelist,
        threadId: this.threadId,
        matchedRules: decision.matchedRules,
        capabilities: decision.capabilities,
        riskScore: decision.riskScore,
        remote,
      }),
      signal,
    );
    await this.audit.append("hitl.decision", auditPayload(argv, decision, remote, { approval }));
    if (approval === "deny") return { block: true, reason: "operator denied command" };
    if (approval === "approve_thread" && !decision.neverWhitelist) {
      this.permissions.allow({ threadId: this.threadId }, argv);
    }
    return undefined;
  }

  private isAlreadyAllowed(decision: PolicyDecision, argv: readonly string[]): boolean {
    return (
      !decision.neverWhitelist && this.permissions.isAllowed({ threadId: this.threadId }, argv)
    );
  }
}

function commandArgvFromToolArgs(args: unknown): string[] {
  if (!args || typeof args !== "object" || !("argv" in args)) {
    throw new Error("command tool args must contain argv");
  }
  const argv = (args as { argv: unknown }).argv;
  if (!Array.isArray(argv)) throw new Error("command tool args must contain argv");
  return argv.map((value) => String(value));
}

function remoteMetadataFromToolArgs(
  args: unknown,
): ReturnType<typeof normalizeRemoteApprovalMetadata> {
  if (!args || typeof args !== "object" || !("remote" in args)) return undefined;
  return normalizeRemoteApprovalMetadata((args as { remote: unknown }).remote);
}

function auditPayload(
  argv: readonly string[],
  decision: PolicyDecision,
  remote: ReturnType<typeof normalizeRemoteApprovalMetadata>,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return remote === undefined ? { argv, decision, ...extra } : { argv, decision, remote, ...extra };
}
