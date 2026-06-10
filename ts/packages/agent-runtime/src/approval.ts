export type ApprovalDecision = "approve_once" | "approve_thread" | "deny" | "pending";

export interface ApprovalRequest {
  argv: string[];
  reason: string | null;
  neverWhitelist: boolean;
  threadId: string;
  matchedRules: string[];
  capabilities: string[];
  riskScore: number;
  remote?: RemoteApprovalMetadata;
}

export interface RemoteApprovalMetadata {
  type: "ssh";
  host: string;
  profileName: string;
  username?: string;
  port?: number;
  knownHostsPath?: string;
  allowedWorkdirs?: string[];
  sudoPolicy?: string;
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
  const request: ApprovalRequest = {
    argv: argv.map((value) => String(value)),
    reason: typeof input.reason === "string" ? input.reason : null,
    neverWhitelist,
    threadId,
    matchedRules: stringArray(input.matchedRules),
    capabilities: stringArray(input.capabilities),
    riskScore: typeof input.riskScore === "number" ? input.riskScore : 0,
  };
  const remote = normalizeRemoteApprovalMetadata(input.remote);
  if (remote !== undefined) request.remote = remote;
  return request;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item));
}

export function normalizeRemoteApprovalMetadata(
  value: unknown,
): RemoteApprovalMetadata | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  if (record.type !== "ssh") return undefined;
  if (typeof record.host !== "string" || record.host.length === 0) return undefined;
  if (typeof record.profileName !== "string" || record.profileName.length === 0) return undefined;
  const metadata: RemoteApprovalMetadata = {
    type: "ssh",
    host: record.host,
    profileName: record.profileName,
  };
  if (typeof record.username === "string") metadata.username = record.username;
  if (typeof record.port === "number" && Number.isInteger(record.port)) metadata.port = record.port;
  if (typeof record.knownHostsPath === "string") metadata.knownHostsPath = record.knownHostsPath;
  const allowedWorkdirs = stringArray(record.allowedWorkdirs);
  if (allowedWorkdirs.length > 0) metadata.allowedWorkdirs = allowedWorkdirs;
  if (typeof record.sudoPolicy === "string") metadata.sudoPolicy = record.sudoPolicy;
  return metadata;
}
