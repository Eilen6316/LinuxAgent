import type { ApprovalRequest, RemoteApprovalMetadata } from "../approval.js";

export const PENDING_APPROVAL_REASON = "operator approval pending";

export type PendingRequestKind =
  | "command_confirmation"
  | "file_patch_confirmation"
  | "ssh_confirmation"
  | "batch_confirmation"
  | "user_input";

export interface PendingRequestBase {
  kind: PendingRequestKind;
  threadId: string;
  requestId: string;
  createdAt: string;
  expiresAt?: string;
  toolCallId?: string;
  auditId?: string;
}

export interface CommandPendingRequest extends PendingRequestBase {
  kind: "command_confirmation";
  argv: string[];
  reason: string | null;
  neverWhitelist: boolean;
  matchedRules: string[];
  capabilities: string[];
  riskScore: number;
  remote?: RemoteApprovalMetadata;
}

export interface FilePatchPendingRequest extends PendingRequestBase {
  kind: "file_patch_confirmation";
  paths: string[];
  riskSummary: string | null;
}

export interface SshPendingRequest extends PendingRequestBase {
  kind: "ssh_confirmation";
  host: string;
  profileName: string;
  argv?: string[];
}

export interface BatchPendingRequest extends PendingRequestBase {
  kind: "batch_confirmation";
  commands: string[][];
}

export interface UserInputPendingRequest extends PendingRequestBase {
  kind: "user_input";
  prompt: string;
}

export type PendingRequest =
  | CommandPendingRequest
  | FilePatchPendingRequest
  | SshPendingRequest
  | BatchPendingRequest
  | UserInputPendingRequest;

export interface CreateCommandPendingRequestInput {
  threadId: string;
  requestId: string;
  argv: readonly string[];
  reason?: string | null;
  neverWhitelist: boolean;
  matchedRules?: readonly string[];
  capabilities?: readonly string[];
  riskScore?: number;
  createdAt?: string;
  expiresAt?: string;
  toolCallId?: string;
  auditId?: string;
  remote?: RemoteApprovalMetadata;
}

export interface PendingRequestSink {
  open(request: PendingRequest): Promise<void>;
  resolve(threadId: string, requestId: string): Promise<void>;
}

export function createCommandPendingRequest(
  input: CreateCommandPendingRequestInput,
): CommandPendingRequest {
  const request: CommandPendingRequest = {
    kind: "command_confirmation",
    threadId: input.threadId,
    requestId: input.requestId,
    argv: input.argv.map((value) => String(value)),
    reason: input.reason ?? null,
    neverWhitelist: input.neverWhitelist,
    matchedRules: [...(input.matchedRules ?? [])],
    capabilities: [...(input.capabilities ?? [])],
    riskScore: input.riskScore ?? 0,
    createdAt: input.createdAt ?? new Date().toISOString(),
  };
  if (input.expiresAt !== undefined) request.expiresAt = input.expiresAt;
  if (input.toolCallId !== undefined) request.toolCallId = input.toolCallId;
  if (input.auditId !== undefined) request.auditId = input.auditId;
  if (input.remote !== undefined) request.remote = input.remote;
  return request;
}

export function commandPendingRequestFromApproval(
  request: ApprovalRequest,
  input: {
    requestId: string;
    createdAt: string;
    expiresAt?: string;
    toolCallId?: string;
    auditId?: string;
  },
): CommandPendingRequest {
  return createCommandPendingRequest({
    threadId: request.threadId,
    requestId: input.requestId,
    argv: request.argv,
    reason: request.reason,
    neverWhitelist: request.neverWhitelist,
    matchedRules: request.matchedRules,
    capabilities: request.capabilities,
    riskScore: request.riskScore,
    createdAt: input.createdAt,
    ...(input.expiresAt !== undefined ? { expiresAt: input.expiresAt } : {}),
    ...(input.toolCallId !== undefined ? { toolCallId: input.toolCallId } : {}),
    ...(input.auditId !== undefined ? { auditId: input.auditId } : {}),
    ...(request.remote !== undefined ? { remote: request.remote } : {}),
  });
}

export function isPendingRequestExpired(request: PendingRequest, now = new Date()): boolean {
  if (request.expiresAt === undefined) return false;
  const expiresAt = Date.parse(request.expiresAt);
  return Number.isFinite(expiresAt) && expiresAt <= now.getTime();
}

export function upsertPendingRequest(
  requests: readonly PendingRequest[],
  request: PendingRequest,
): PendingRequest[] {
  const next = requests.filter((item) => item.requestId !== request.requestId);
  next.push(request);
  return next;
}

export function removePendingRequest(
  requests: readonly PendingRequest[],
  threadId: string,
  requestId: string,
): PendingRequest[] {
  return requests.filter(
    (request) => request.threadId !== threadId || request.requestId !== requestId,
  );
}

export function activePendingRequests(
  requests: readonly PendingRequest[],
  now = new Date(),
): PendingRequest[] {
  return requests.filter((request) => !isPendingRequestExpired(request, now));
}
