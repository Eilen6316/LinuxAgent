import { createHash } from "node:crypto";

export interface AuditEntry {
  timestamp: string;
  eventType: string;
  payload: Record<string, unknown>;
  prevHash: string | null;
  hash: string;
}

export function computeAuditHash(entry: Omit<AuditEntry, "hash">): string {
  return createHash("sha256").update(JSON.stringify(entry)).digest("hex");
}

export function createAuditEntry(
  eventType: string,
  payload: Record<string, unknown>,
  prevHash: string | null,
  now = new Date(),
): AuditEntry {
  const base = { timestamp: now.toISOString(), eventType, payload, prevHash };
  return { ...base, hash: computeAuditHash(base) };
}
