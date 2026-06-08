import type { FilePatchPlan } from "../../../contracts/src/index.js";

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
    operation: plan.requestIntent,
    success: false,
    rolledBack: false,
  });
  if (denied) return { applied: false, rolledBack: false, changedPaths: [] };
  throw new Error(
    "transactional apply must be implemented with snapshot and rollback before enabling file patch writes",
  );
}
