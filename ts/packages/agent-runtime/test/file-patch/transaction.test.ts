import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { FilePatchPlan } from "../../../contracts/src/index.js";

import { applyFilePatchTransaction } from "../../src/file-patch/transaction.js";

class RecordingAudit {
  readonly events: Array<{ eventType: string; payload: Record<string, unknown> }> = [];

  async append(eventType: string, payload: Record<string, unknown>): Promise<void> {
    this.events.push({ eventType, payload });
  }
}

describe("file patch transaction", () => {
  it("does not write files until snapshot and rollback are implemented", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    const target = join(dir, "example.txt");
    await writeFile(target, "old\n", "utf8");
    const audit = new RecordingAudit();
    const plan = planFor(target);

    await expect(
      applyFilePatchTransaction(plan, { approvePatch: async () => "approve" }, audit),
    ).rejects.toThrow("snapshot and rollback");

    await expect(readFile(target, "utf8")).resolves.toBe("old\n");
    expect(audit.events).toEqual([
      {
        eventType: "file_patch.decision",
        payload: {
          decision: "approve",
          paths: [target],
          operation: "update",
          success: false,
          rolledBack: false,
        },
      },
    ]);
  });

  it("returns without writing when approval denies the patch", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    const target = join(dir, "example.txt");
    await writeFile(target, "old\n", "utf8");
    const audit = new RecordingAudit();

    await expect(
      applyFilePatchTransaction(planFor(target), { approvePatch: async () => "deny" }, audit),
    ).resolves.toEqual({ applied: false, rolledBack: false, changedPaths: [] });

    await expect(readFile(target, "utf8")).resolves.toBe("old\n");
    expect(audit.events[0]).toMatchObject({
      eventType: "file_patch.decision",
      payload: {
        decision: "deny",
        paths: [target],
        operation: "update",
        success: false,
        rolledBack: false,
      },
    });
  });
});

function planFor(path: string): FilePatchPlan {
  return {
    version: 1,
    requestIntent: "update",
    summary: "update example",
    patches: [
      {
        path,
        diff: `--- ${path}\n+++ ${path}\n@@ -1 +1 @@\n-old\n+new\n`,
      },
    ],
  };
}
