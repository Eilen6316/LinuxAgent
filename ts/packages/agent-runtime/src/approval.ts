export type ApprovalDecision = "approve_once" | "approve_thread" | "deny";

export interface ApprovalRequest {
  argv: string[];
  reason: string | null;
  neverWhitelist: boolean;
  threadId: string;
  matchedRules: string[];
  capabilities: string[];
  riskScore: number;
}

export interface ApprovalPort {
  requestApproval(request: ApprovalRequest, signal?: AbortSignal): Promise<ApprovalDecision>;
}

export class NonTtyApprovalPort implements ApprovalPort {
  async requestApproval(request: ApprovalRequest, signal?: AbortSignal): Promise<ApprovalDecision> {
    void request;
    void signal;
    return "deny";
  }
}

export function createApprovalRequest(input: Record<string, unknown>): ApprovalRequest {
  const argv = input.argv;
  if (!Array.isArray(argv) || argv.length === 0) {
    throw new Error("approval request requires argv");
  }
  const neverWhitelist = input.neverWhitelist;
  if (typeof neverWhitelist !== "boolean") {
    throw new Error("approval request requires neverWhitelist");
  }
  const threadId = input.threadId;
  if (typeof threadId !== "string" || threadId.length === 0) {
    throw new Error("approval request requires threadId");
  }
  return {
    argv: argv.map((value) => String(value)),
    reason: typeof input.reason === "string" ? input.reason : null,
    neverWhitelist,
    threadId,
    matchedRules: stringArray(input.matchedRules),
    capabilities: stringArray(input.capabilities),
    riskScore: typeof input.riskScore === "number" ? input.riskScore : 0,
  };
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item));
}
