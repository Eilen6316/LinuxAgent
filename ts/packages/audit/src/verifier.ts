import { readFile } from "node:fs/promises";
import { type AuditEntry, computeAuditHash } from "./hash-chain.js";

export type AuditVerifyResult =
  | { status: "missing"; entries: [] }
  | { status: "valid"; entries: AuditEntry[] }
  | { status: "invalid"; entries: AuditEntry[]; line: number; reason: string };

export async function verifyAuditLog(path: string): Promise<AuditVerifyResult> {
  let text: string;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return { status: "missing", entries: [] };
    }
    throw error;
  }

  const entries: AuditEntry[] = [];
  const lines = text.split("\n").filter((line) => line.length > 0);
  let prevHash: string | null = null;

  for (let index = 0; index < lines.length; index += 1) {
    const lineNumber = index + 1;
    const line = lines[index];
    if (line === undefined) continue;
    let entry: AuditEntry;
    try {
      entry = JSON.parse(line) as AuditEntry;
    } catch {
      return { status: "invalid", entries, line: lineNumber, reason: "malformed JSON" };
    }
    const { hash, ...withoutHash } = entry;
    if (computeAuditHash(withoutHash) !== hash) {
      return { status: "invalid", entries, line: lineNumber, reason: "hash mismatch" };
    }
    if (entry.prevHash !== prevHash) {
      return { status: "invalid", entries, line: lineNumber, reason: "prevHash mismatch" };
    }
    entries.push(entry);
    prevHash = entry.hash;
  }

  return { status: "valid", entries };
}
