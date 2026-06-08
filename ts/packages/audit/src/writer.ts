import { mkdir, open, stat } from "node:fs/promises";
import { dirname } from "node:path";
import { type AuditEntry, createAuditEntry } from "./hash-chain.js";
import { verifyAuditLog } from "./verifier.js";

export class AuditPermissionError extends Error {}

export class AuditWriter {
  constructor(private readonly path: string) {}

  async append(eventType: string, payload: Record<string, unknown>): Promise<AuditEntry> {
    await mkdir(dirname(this.path), { recursive: true, mode: 0o700 });
    const prevHash = await this.lastHash();
    const entry = createAuditEntry(eventType, payload, prevHash);
    await this.assertSafeExistingMode();
    const handle = await open(this.path, "a", 0o600);
    try {
      await handle.appendFile(`${JSON.stringify(entry)}\n`, "utf8");
    } finally {
      await handle.close();
    }
    return entry;
  }

  private async assertSafeExistingMode(): Promise<void> {
    try {
      const mode = (await stat(this.path)).mode & 0o777;
      if ((mode & 0o077) !== 0) {
        throw new AuditPermissionError(
          `audit log mode must be 0600-compatible, got ${mode.toString(8)}`,
        );
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }
  }

  private async lastHash(): Promise<string | null> {
    const result = await verifyAuditLog(this.path);
    if (result.status === "missing") return null;
    if (result.status !== "valid") {
      throw new Error(`cannot append to invalid audit log: ${result.reason}`);
    }
    if (result.entries.length === 0) return null;
    return result.entries.at(-1)?.hash ?? null;
  }
}
