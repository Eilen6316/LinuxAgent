import { approvalOptions } from "./approval-selector.js";
import type { HitlRequest } from "./event-renderer.js";

export function renderHitlOverlay(request: HitlRequest): string[] {
  const lines = [
    `Approval ${request.requestId}`,
    `command: ${request.argv.join(" ")}`,
    `goal: ${request.goal}`,
    `purpose: ${request.purpose}`,
    `policy: ${request.policy.level} risk=${request.policy.riskScore}`,
    `reason: ${request.policy.reason ?? ""}`,
    `capabilities: ${request.policy.capabilities.join(", ")}`,
    `matched_rules: ${request.policy.matchedRules.join(", ")}`,
    `sandbox: profile=${request.sandbox.profile} runner=${request.sandbox.runner} enforced=${request.sandbox.enforced}`,
    `choices: ${approvalOptions(request.policy).map(renderChoice).join("  ")}`,
  ];
  if (request.remote !== undefined) {
    lines.splice(9, 0, renderRemote(request.remote));
  }
  return lines;
}

function renderChoice(option: ReturnType<typeof approvalOptions>[number]): string {
  switch (option.decision) {
    case "approve_once":
      return "[y] Yes";
    case "approve_thread":
      return "[a] Yes, don't ask again";
    case "deny":
      return "[n] No";
    case "pending":
      return "[ ] Pending";
  }
}

function renderRemote(remote: NonNullable<HitlRequest["remote"]>): string {
  return [
    `remote: type=${remote.type} host=${remote.host} profile=${remote.profileName}`,
    `user=${remote.username ?? ""}`,
    `port=${remote.port ?? ""}`,
    `known_hosts=${remote.knownHostsPath ?? ""}`,
    `workdirs=${remote.allowedWorkdirs?.join(",") ?? ""}`,
    `sudo=${remote.sudoPolicy ?? ""}`,
  ].join(" ");
}
