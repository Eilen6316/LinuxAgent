import { chmod, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { computeAuditHash, createAuditEntry } from "../src/hash-chain.js";
import { verifyAuditLog } from "../src/verifier.js";
import { AuditPermissionError, AuditWriter } from "../src/writer.js";

describe("audit hash chain", () => {
  it("changes hash when payload changes", () => {
    const entry = createAuditEntry(
      "hitl.decision",
      { decision: "approve" },
      null,
      new Date("2026-06-08T00:00:00Z"),
    );
    const { hash: _hash, ...withoutHash } = entry;
    const tampered = { ...withoutHash, payload: { decision: "deny" } };

    expect(computeAuditHash(tampered)).not.toBe(entry.hash);
  });

  it("writes JSONL with 0600 mode and verifies the chain", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-audit-"));
    const path = join(dir, "audit.log");
    const writer = new AuditWriter(path);

    await writer.append("hitl.decision", { decision: "approve" });
    await writer.append("policy.allow", { argv: ["uname", "-a"] });

    const mode = (await stat(path)).mode & 0o777;
    expect(mode).toBe(0o600);
    const result = await verifyAuditLog(path);
    expect(result.status).toBe("valid");
    if (result.status === "valid") {
      expect(result.entries).toHaveLength(2);
      expect(result.entries[1]?.prevHash).toBe(result.entries[0]?.hash);
    }
  });

  it("refuses group-readable existing audit file", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-audit-"));
    const path = join(dir, "audit.log");
    await writeFile(path, "", { mode: 0o644 });
    await chmod(path, 0o644);

    await expect(new AuditWriter(path).append("hitl.decision", {})).rejects.toBeInstanceOf(
      AuditPermissionError,
    );
  });

  it("detects malformed JSON before appending", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-audit-"));
    const path = join(dir, "audit.log");
    await writeFile(path, "{not-json}\n", { mode: 0o600 });

    await expect(new AuditWriter(path).append("hitl.decision", {})).rejects.toThrow(
      "cannot append to invalid audit log",
    );
    expect((await readFile(path, "utf8")).trim()).toBe("{not-json}");
  });

  it("reports hash mismatch and prevHash mismatch", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-audit-"));
    const hashMismatchPath = join(dir, "hash.log");
    const first = createAuditEntry("hitl.decision", { decision: "approve" }, null);
    await writeFile(
      hashMismatchPath,
      `${JSON.stringify({ ...first, payload: { decision: "deny" } })}\n`,
      { mode: 0o600 },
    );

    expect(await verifyAuditLog(hashMismatchPath)).toMatchObject({
      status: "invalid",
      line: 1,
      reason: "hash mismatch",
    });

    const prevMismatchPath = join(dir, "prev.log");
    const second = createAuditEntry("policy.allow", {}, "bad-prev");
    await writeFile(prevMismatchPath, `${JSON.stringify(second)}\n`, { mode: 0o600 });

    expect(await verifyAuditLog(prevMismatchPath)).toMatchObject({
      status: "invalid",
      line: 1,
      reason: "prevHash mismatch",
    });
  });
});
