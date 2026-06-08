import type { PolicyDecision } from "../../contracts/src/index.js";

export interface ConfirmationSandbox {
  profile: string;
  runner: string;
  enforced: boolean;
}

export interface ConfirmationPayload {
  argv: readonly string[];
  policy: PolicyDecision;
  sandbox: ConfirmationSandbox;
}

export function renderConfirmation(payload: ConfirmationPayload): string {
  return [
    `argv: ${payload.argv.join(" ")}`,
    `policy: ${payload.policy.level}`,
    `reason: ${payload.policy.reason ?? ""}`,
    `capabilities: ${payload.policy.capabilities.join(", ")}`,
    `matched_rules: ${payload.policy.matchedRules.join(", ")}`,
    `sandbox: profile=${payload.sandbox.profile} runner=${payload.sandbox.runner} enforced=${payload.sandbox.enforced}`,
    `never_whitelist: ${payload.policy.neverWhitelist}`,
  ].join("\n");
}
