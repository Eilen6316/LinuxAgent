import { randomUUID } from "node:crypto";
import type { PolicyDecision } from "@linuxagent/contracts";
import type { PolicyEngine } from "@linuxagent/policy";
import {
  type ApprovalPort,
  createApprovalRequest,
  normalizeRemoteApprovalMetadata,
} from "./approval.js";
import {
  commandPendingRequestFromApproval,
  PENDING_APPROVAL_REASON,
  type PendingRequestSink,
} from "./react/pending-request.js";
import type { PermissionScope, SessionPermissions } from "./session-permissions.js";

export interface ToolCallContext {
  args: unknown;
  toolCallId?: string;
}

export interface ToolCallResult {
  block: true;
  reason: string;
}

export interface AuditPort {
  append(eventType: string, payload: Record<string, unknown>): Promise<void>;
}

export interface LinuxAgentToolGateOptions {
  permissionScope?: PermissionScope;
  pendingRequests?: PendingRequestSink;
  now?: () => Date;
  approvalExpiresInMs?: number;
}

export class LinuxAgentToolGate {
  private readonly permissionScope: PermissionScope;
  private readonly pendingRequests: PendingRequestSink | undefined;
  private readonly now: () => Date;
  private readonly approvalExpiresInMs: number | undefined;

  constructor(
    private readonly policy: Pick<PolicyEngine, "evaluate">,
    private readonly permissions: SessionPermissions,
    private readonly approvals: ApprovalPort,
    private readonly audit: AuditPort,
    threadId: string,
    options: LinuxAgentToolGateOptions = {},
  ) {
    this.permissionScope = options.permissionScope ?? { threadId };
    this.pendingRequests = options.pendingRequests;
    this.now = options.now ?? (() => new Date());
    this.approvalExpiresInMs = options.approvalExpiresInMs;
  }

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

    const approvalRequest = createApprovalRequest({
      argv,
      reason: decision.reason,
      neverWhitelist: decision.neverWhitelist,
      threadId: this.sessionThreadId(),
      matchedRules: decision.matchedRules,
      capabilities: decision.capabilities,
      riskScore: decision.riskScore,
      remote,
    });
    const requestId = randomUUID();
    const expiresAt = this.expiresAt();
    await this.pendingRequests?.open(
      commandPendingRequestFromApproval(approvalRequest, {
        requestId,
        createdAt: this.now().toISOString(),
        ...(expiresAt !== undefined ? { expiresAt } : {}),
        ...(context.toolCallId !== undefined ? { toolCallId: context.toolCallId } : {}),
        auditId: requestId,
      }),
    );

    const approval = await this.approvals.requestApproval(approvalRequest, signal);
    if (approval === "pending") {
      await this.audit.append("hitl.pending", auditPayload(argv, decision, remote, { requestId }));
      return { block: true, reason: PENDING_APPROVAL_REASON };
    }

    await this.pendingRequests?.resolve(approvalRequest.threadId, requestId);
    await this.audit.append(
      "hitl.decision",
      auditPayload(argv, decision, remote, { approval, requestId }),
    );
    if (approval === "deny") return { block: true, reason: "operator denied command" };
    if (approval === "approve_thread" && !decision.neverWhitelist) {
      this.permissions.allow(this.permissionScope, argv);
    }
    return undefined;
  }

  private isAlreadyAllowed(decision: PolicyDecision, argv: readonly string[]): boolean {
    return !decision.neverWhitelist && this.permissions.isAllowed(this.permissionScope, argv);
  }

  private sessionThreadId(): string {
    return this.permissionScope.resumedFromThreadId ?? this.permissionScope.threadId;
  }

  private expiresAt(): string | undefined {
    if (this.approvalExpiresInMs === undefined) return undefined;
    return new Date(this.now().getTime() + this.approvalExpiresInMs).toISOString();
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
