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
  it("applies approved patches transactionally", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    const target = join(dir, "example.txt");
    await writeFile(target, "old\n", "utf8");
    const audit = new RecordingAudit();
    const plan = planFor(target);

    await expect(
      applyFilePatchTransaction(plan, { approvePatch: async () => "approve" }, audit),
    ).resolves.toEqual({ applied: true, rolledBack: false, changedPaths: [target] });

    await expect(readFile(target, "utf8")).resolves.toBe("new\n");
    expect(audit.events.at(-1)).toMatchObject({
      eventType: "file_patch.result",
      payload: {
        success: true,
        rolledBack: false,
        changedPaths: [target],
      },
    });
  });

  it("rolls back already-written files when a later patch fails", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    const first = join(dir, "first.txt");
    const second = join(dir, "second.txt");
    await writeFile(first, "old\n", "utf8");
    await writeFile(second, "stable\n", "utf8");
    const audit = new RecordingAudit();

    await expect(
      applyFilePatchTransaction(
        {
          version: 1,
          requestIntent: "update",
          summary: "partial failure",
          patches: [
            {
              path: first,
              diff: `--- ${first}\n+++ ${first}\n@@ -1 +1 @@\n-old\n+new\n`,
            },
            {
              path: second,
              diff: `--- ${second}\n+++ ${second}\n@@ -1 +1 @@\n-missing\n+changed\n`,
            },
          ],
        },
        { approvePatch: async () => "approve" },
        audit,
      ),
    ).rejects.toThrow("hunk removal mismatch");

    await expect(readFile(first, "utf8")).resolves.toBe("old\n");
    await expect(readFile(second, "utf8")).resolves.toBe("stable\n");
    expect(audit.events.at(-1)).toMatchObject({
      eventType: "file_patch.result",
      payload: {
        success: false,
        rolledBack: true,
        changedPaths: [first],
      },
    });
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
