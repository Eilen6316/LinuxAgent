import type { ApprovalDecision } from "@linuxagent/agent-runtime";
import type { PolicyDecision } from "@linuxagent/contracts";

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
