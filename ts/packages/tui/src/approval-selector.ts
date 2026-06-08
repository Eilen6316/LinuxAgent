import type { ApprovalDecision } from "../../agent-runtime/src/index.js";
import type { PolicyDecision } from "../../contracts/src/index.js";

export interface ApprovalOption {
  label: "Yes" | "Yes, don't ask again" | "No";
  decision: ApprovalDecision;
}

export function approvalOptions(policy: Pick<PolicyDecision, "neverWhitelist">): ApprovalOption[] {
  const options: ApprovalOption[] = [{ label: "Yes", decision: "approve_once" }];
  if (!policy.neverWhitelist) {
    options.push({ label: "Yes, don't ask again", decision: "approve_thread" });
  }
  options.push({ label: "No", decision: "deny" });
  return options;
}
