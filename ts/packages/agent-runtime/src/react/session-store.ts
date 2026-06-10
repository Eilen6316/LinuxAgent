import { chmod, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { redactOutput } from "@linuxagent/executor";
import type { SessionPermissionsSnapshot } from "../session-permissions.js";
import {
  activePendingRequests,
  type PendingRequest,
  removePendingRequest,
  upsertPendingRequest,
} from "./pending-request.js";

export interface ReactSessionMessageSnapshot {
  role: "system" | "user" | "assistant" | "tool";
  text: string;
  metadata?: Record<string, JsonValue>;
}

export interface ReactSessionRecord {
  threadId: string;
  messages: ReactSessionMessageSnapshot[];
  pendingRequests: PendingRequest[];
  permissions: SessionPermissionsSnapshot;
  updatedAt: string;
}

export interface ReactSessionStore {
  load(threadId: string): Promise<ReactSessionRecord | null>;
  save(record: ReactSessionRecord): Promise<void>;
}

type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };

interface ReactSessionStoreFile {
  version: 1;
  sessions: Record<string, ReactSessionRecord>;
}

export class JsonReactSessionStore implements ReactSessionStore {
  constructor(readonly path: string) {}

  async load(threadId: string): Promise<ReactSessionRecord | null> {
    const file = await this.readFile();
    return file.sessions[threadId] ?? null;
  }

  async save(record: ReactSessionRecord): Promise<void> {
    const file = await this.readFile();
    file.sessions[record.threadId] = sanitizeSessionRecord(record);
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    await writeFile(this.path, `${JSON.stringify(file, null, 2)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
    await chmod(this.path, 0o600);
  }

  private async readFile(): Promise<ReactSessionStoreFile> {
    if (!(await exists(this.path))) return { version: 1, sessions: {} };
    const raw = await readFile(this.path, "utf8");
    if (raw.trim().length === 0) return { version: 1, sessions: {} };
    const parsed = JSON.parse(raw) as Partial<ReactSessionStoreFile>;
    if (parsed.version !== 1 || parsed.sessions === undefined) {
      throw new Error("unsupported React session store format");
    }
    return { version: 1, sessions: parsed.sessions };
  }
}

export function pendingRequestsForResume(
  record: ReactSessionRecord | null,
  now = new Date(),
): PendingRequest[] {
  return activePendingRequests(record?.pendingRequests ?? [], now);
}

export function withPendingRequest(
  record: ReactSessionRecord,
  request: PendingRequest,
): ReactSessionRecord {
  return {
    ...record,
    pendingRequests: upsertPendingRequest(record.pendingRequests, request),
  };
}

export function withoutPendingRequest(
  record: ReactSessionRecord,
  threadId: string,
  requestId: string,
): ReactSessionRecord {
  return {
    ...record,
    pendingRequests: removePendingRequest(record.pendingRequests, threadId, requestId),
  };
}

function sanitizeSessionRecord(record: ReactSessionRecord): ReactSessionRecord {
  return {
    ...record,
    messages: record.messages.map((message) => {
      const sanitized: ReactSessionMessageSnapshot = {
        role: message.role,
        text: redactOutput(message.text).text,
      };
      if (message.metadata !== undefined) sanitized.metadata = sanitizeMetadata(message.metadata);
      return sanitized;
    }),
  };
}

function sanitizeMetadata(metadata: Record<string, JsonValue>): Record<string, JsonValue> {
  const sanitized: Record<string, JsonValue> = {};
  for (const [key, value] of Object.entries(metadata)) {
    sanitized[key] = sensitiveKey(key) ? "[REDACTED]" : sanitizeJsonValue(value);
  }
  return sanitized;
}

function sanitizeJsonValue(value: JsonValue): JsonValue {
  if (typeof value === "string") return redactOutput(value).text;
  if (Array.isArray(value)) return value.map((item) => sanitizeJsonValue(item));
  if (value === null || typeof value !== "object") return value;
  const sanitized: Record<string, JsonValue> = {};
  for (const [key, child] of Object.entries(value)) {
    sanitized[key] = sensitiveKey(key) ? "[REDACTED]" : sanitizeJsonValue(child);
  }
  return sanitized;
}

function sensitiveKey(key: string): boolean {
  return /(?:authorization|api[_-]?key|password|secret|token|private[_-]?key)/i.test(key);
}

async function exists(path: string): Promise<boolean> {
  try {
    await stat(path);
    return true;
  } catch (error) {
    if (error instanceof Error && "code" in error && error.code === "ENOENT") return false;
    throw error;
  }
}
