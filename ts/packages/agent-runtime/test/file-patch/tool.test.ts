import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { FilePatchPlan } from "../../../contracts/src/index.js";
import type { PatchApprovalPort } from "../../src/file-patch/index.js";
import { executeFilePatchTool } from "../../src/file-patch/index.js";
import type { PatchAuditPort } from "../../src/file-patch/transaction.js";

class RecordingPatchApproval implements PatchApprovalPort {
  readonly previews: string[] = [];

  constructor(private readonly decision: "approve" | "deny") {}

  async approvePatch(_plan: FilePatchPlan, preview: string): Promise<"approve" | "deny"> {
    this.previews.push(preview);
    return this.decision;
  }
}

class RecordingAudit implements PatchAuditPort {
  readonly events: Array<{ eventType: string; payload: Record<string, unknown> }> = [];

  async append(eventType: string, payload: Record<string, unknown>): Promise<void> {
    this.events.push({ eventType, payload });
  }
}

describe("executeFilePatchTool", () => {
  it("applies approved patches through path policy and audit", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-tool-"));
    const target = join(dir, "example.txt");
    await writeFile(target, "old\n", "utf8");
    const approval = new RecordingPatchApproval("approve");
    const audit = new RecordingAudit();

    const result = await executeFilePatchTool({
      args: planFor(target),
      pathPolicy: { allowedRoots: [dir] },
      approval,
      audit,
    });

    expect(result).toMatchObject({
      executed: true,
      applied: true,
      rolledBack: false,
      changedPaths: [target],
    });
    await expect(readFile(target, "utf8")).resolves.toBe("new\n");
    expect(approval.previews).toHaveLength(1);
    expect(audit.events.map((event) => event.eventType)).toEqual([
      "file_patch.decision",
      "file_patch.result",
    ]);
    expect(result.modelText).toContain("file_patch applied=true");
    expect(result.modelText).not.toContain("-old");
  });

  it("returns without writing when approval denies the patch", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-tool-"));
    const target = join(dir, "example.txt");
    await writeFile(target, "old\n", "utf8");
    const approval = new RecordingPatchApproval("deny");
    const audit = new RecordingAudit();

    const result = await executeFilePatchTool({
      args: planFor(target),
      pathPolicy: { allowedRoots: [dir] },
      approval,
      audit,
    });

    expect(result).toMatchObject({
      executed: true,
      applied: false,
      rolledBack: false,
      changedPaths: [],
    });
    await expect(readFile(target, "utf8")).resolves.toBe("old\n");
    expect(approval.previews).toHaveLength(1);
    expect(audit.events[0]).toMatchObject({
      eventType: "file_patch.decision",
      payload: { decision: "deny", paths: [target] },
    });
  });

  it("fails closed before approval when a target path is outside allowed roots", async () => {
    const allowed = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-allowed-"));
    const outside = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-outside-"));
    const target = join(outside, "example.txt");
    await writeFile(target, "old\n", "utf8");
    const approval = new RecordingPatchApproval("approve");
    const audit = new RecordingAudit();

    const result = await executeFilePatchTool({
      args: planFor(target),
      pathPolicy: { allowedRoots: [allowed] },
      approval,
      audit,
    });

    expect(result).toMatchObject({
      executed: false,
      applied: false,
      rolledBack: false,
      changedPaths: [],
    });
    if (result.executed) {
      throw new Error("expected file patch tool to block disallowed path");
    }
    expect(result.blockedReason).toContain("path outside allowed roots");
    await expect(readFile(target, "utf8")).resolves.toBe("old\n");
    expect(approval.previews).toHaveLength(0);
    expect(audit.events[0]).toMatchObject({
      eventType: "file_patch.block",
      payload: { reason: expect.stringContaining("path outside allowed roots") },
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
