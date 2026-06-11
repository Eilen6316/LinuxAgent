import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import type { FilePatchPlan } from "@linuxagent/contracts";
import { validateUnifiedDiff } from "./diff-validator.js";

export interface PatchApprovalPort {
  approvePatch(plan: FilePatchPlan, preview: string): Promise<"approve" | "deny">;
}

export interface PatchAuditPort {
  append(eventType: string, payload: Record<string, unknown>): Promise<void>;
}

export interface FilePatchTransactionResult {
  applied: boolean;
  rolledBack: boolean;
  changedPaths: string[];
}

export async function applyFilePatchTransaction(
  plan: FilePatchPlan,
  approval: PatchApprovalPort,
  audit: PatchAuditPort,
): Promise<FilePatchTransactionResult> {
  const paths = plan.patches.map((patch) => patch.path);
  const preview = plan.patches.map((patch) => `--- ${patch.path}\n${patch.diff}`).join("\n");
  const decision = await approval.approvePatch(plan, preview);
  const denied = decision === "deny";
  await audit.append("file_patch.decision", {
    decision,
    paths,
    acceptedPaths: denied ? [] : paths,
    rejectedPaths: denied ? paths : [],
    operation: plan.requestIntent,
    success: false,
    rolledBack: false,
  });
  if (denied) return { applied: false, rolledBack: false, changedPaths: [] };

  const snapshots = new Map<string, string>();
  const changedPaths: string[] = [];
  try {
    for (const patch of plan.patches) {
      validateUnifiedDiff(patch.diff);
      const original = snapshots.get(patch.path) ?? (await readFile(patch.path, "utf8"));
      snapshots.set(patch.path, original);
      const updated = applyUnifiedDiff(original, patch.diff);
      await writeFile(patch.path, updated, "utf8");
      changedPaths.push(patch.path);
    }
    await audit.append("file_patch.result", {
      success: true,
      rolledBack: false,
      changedPaths,
      backupHashes: backupHashes(snapshots),
    });
    return { applied: true, rolledBack: false, changedPaths };
  } catch (error) {
    for (const [path, content] of snapshots) {
      await writeFile(path, content, "utf8");
    }
    await audit.append("file_patch.result", {
      success: false,
      rolledBack: snapshots.size > 0,
      changedPaths,
      backupHashes: backupHashes(snapshots),
      reason: error instanceof Error ? error.message : String(error),
    });
    throw error;
  }
}

function backupHashes(
  snapshots: ReadonlyMap<string, string>,
): Array<{ path: string; sha256: string }> {
  return [...snapshots.entries()].map(([path, content]) => ({
    path,
    sha256: createHash("sha256").update(content, "utf8").digest("hex"),
  }));
}

function applyUnifiedDiff(original: string, diff: string): string {
  const lines = original.split("\n");
  const output = [...lines];
  const diffLines = diff.split(/\r?\n/);
  let cursor = 0;

  while (cursor < diffLines.length) {
    const line = diffLines[cursor];
    if (!line?.startsWith("@@ ")) {
      cursor += 1;
      continue;
    }
    const hunk = parseHunkHeader(line);
    let position = hunk.oldStart - 1;
    cursor += 1;
    while (
      cursor < diffLines.length &&
      !diffLines[cursor]?.startsWith("@@ ") &&
      !diffLines[cursor]?.startsWith("--- ")
    ) {
      const hunkLine = diffLines[cursor] ?? "";
      cursor += 1;
      if (hunkLine === "" || hunkLine.startsWith("\\")) continue;
      const marker = hunkLine[0];
      const text = hunkLine.slice(1);
      if (marker === " ") {
        assertLine(output, position, text, "hunk context mismatch");
        position += 1;
      } else if (marker === "-") {
        assertLine(output, position, text, "hunk removal mismatch");
        output.splice(position, 1);
      } else if (marker === "+") {
        output.splice(position, 0, text);
        position += 1;
      }
    }
  }

  return output.join("\n");
}

function parseHunkHeader(header: string): { oldStart: number } {
  const match = /^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@/.exec(header);
  if (!match?.[1]) throw new Error(`invalid hunk header: ${header}`);
  return { oldStart: Number.parseInt(match[1], 10) };
}

function assertLine(
  lines: readonly string[],
  position: number,
  expected: string,
  message: string,
): void {
  if (lines[position] !== expected) {
    throw new Error(
      `${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(lines[position])}`,
    );
  }
}
