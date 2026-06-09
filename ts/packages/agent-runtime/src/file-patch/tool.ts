import type { FilePatchPlan } from "@linuxagent/contracts";
import { FilePatchPlanSchema } from "@linuxagent/contracts";
import { Value } from "typebox/value";
import { assertModeSafe, assertPathAllowed, type PathPolicy } from "./path-policy.js";
import {
  applyFilePatchTransaction,
  type FilePatchTransactionResult,
  type PatchApprovalPort,
  type PatchAuditPort,
} from "./transaction.js";

export interface ExecuteFilePatchToolInput {
  args: unknown;
  pathPolicy: PathPolicy;
  approval: PatchApprovalPort;
  audit: PatchAuditPort;
}

export type ExecuteFilePatchToolResult =
  | {
      executed: false;
      applied: false;
      rolledBack: false;
      changedPaths: [];
      blockedReason: string;
      modelText: string;
    }
  | ({
      executed: true;
      modelText: string;
    } & FilePatchTransactionResult);

export async function executeFilePatchTool(
  input: ExecuteFilePatchToolInput,
): Promise<ExecuteFilePatchToolResult> {
  const plan = parseFilePatchPlan(input.args);
  const pathResult = await normalizePlanPaths(plan, input.pathPolicy);
  if (!pathResult.ok) {
    await input.audit.append("file_patch.block", {
      reason: pathResult.reason,
      operation: plan.requestIntent,
      paths: plan.patches.map((patch) => patch.path),
    });
    return {
      executed: false,
      applied: false,
      rolledBack: false,
      changedPaths: [],
      blockedReason: pathResult.reason,
      modelText: `blocked: ${pathResult.reason}`,
    };
  }

  const result = await applyFilePatchTransaction(pathResult.plan, input.approval, input.audit);
  return {
    executed: true,
    ...result,
    modelText: formatPatchResultForModel(result),
  };
}

function parseFilePatchPlan(args: unknown): FilePatchPlan {
  if (!Value.Check(FilePatchPlanSchema, args)) {
    throw new Error("file patch tool args must match FilePatchPlanSchema");
  }
  return args;
}

async function normalizePlanPaths(
  plan: FilePatchPlan,
  policy: PathPolicy,
): Promise<{ ok: true; plan: FilePatchPlan } | { ok: false; reason: string }> {
  try {
    const patches = [];
    for (const patch of plan.patches) {
      patches.push({ ...patch, path: await assertPathAllowed(patch.path, policy) });
    }
    const permissionChanges = [];
    for (const change of plan.permissionChanges ?? []) {
      assertModeSafe(change.mode);
      permissionChanges.push({ ...change, path: await assertPathAllowed(change.path, policy) });
    }
    return {
      ok: true,
      plan:
        permissionChanges.length > 0
          ? { ...plan, patches, permissionChanges }
          : { ...plan, patches },
    };
  } catch (error) {
    return { ok: false, reason: error instanceof Error ? error.message : String(error) };
  }
}

function formatPatchResultForModel(result: FilePatchTransactionResult): string {
  return [
    `file_patch applied=${result.applied}`,
    `rolled_back=${result.rolledBack}`,
    `changed_paths=${JSON.stringify(result.changedPaths)}`,
  ].join("\n");
}
