import { SessionPermissions } from "../session-permissions.js";
import type { PendingRequest } from "./pending-request.js";
import {
  pendingRequestsForResume,
  type ReactSessionMessageSnapshot,
  type ReactSessionStore,
} from "./session-store.js";

export interface ReactResumeInput {
  store: ReactSessionStore;
  threadId: string;
  now?: Date;
}

export interface ReactResumeContext {
  threadId: string;
  messages: ReactSessionMessageSnapshot[];
  pendingRequest: PendingRequest | undefined;
  permissions: SessionPermissions;
}

export async function resumeReactSession(input: ReactResumeInput): Promise<ReactResumeContext> {
  const record = await input.store.load(input.threadId);
  const pendingRequests = pendingRequestsForResume(record, input.now);
  return {
    threadId: input.threadId,
    messages: record?.messages ?? [],
    pendingRequest: pendingRequests[0],
    permissions: SessionPermissions.fromSnapshot(record?.permissions),
  };
}
