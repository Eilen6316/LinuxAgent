import type { PolicyDecision } from "@linuxagent/contracts";

export interface ConfirmationSandbox {
  profile: string;
  runner: string;
  enforced: boolean;
}

export interface ConfirmationPayload {
  argv: readonly string[];
  policy: PolicyDecision;
  sandbox: ConfirmationSandbox;
  remote?: ConfirmationRemote;
}

export interface ConfirmationRemote {
  type: "ssh";
  host: string;
  profileName: string;
  username?: string;
  port?: number;
  knownHostsPath?: string;
  allowedWorkdirs?: readonly string[];
  sudoPolicy?: string;
}

export function renderConfirmation(payload: ConfirmationPayload): string {
  const lines = [
    `argv: ${payload.argv.join(" ")}`,
    `policy: ${payload.policy.level}`,
    `reason: ${payload.policy.reason ?? ""}`,
    `capabilities: ${payload.policy.capabilities.join(", ")}`,
    `matched_rules: ${payload.policy.matchedRules.join(", ")}`,
    `sandbox: profile=${payload.sandbox.profile} runner=${payload.sandbox.runner} enforced=${payload.sandbox.enforced}`,
    `never_whitelist: ${payload.policy.neverWhitelist}`,
  ];
  if (payload.remote !== undefined) {
    lines.push(renderRemote(payload.remote));
  }
  return lines.join("\n");
}

function renderRemote(remote: ConfirmationRemote): string {
  return [
    `remote: type=${remote.type} host=${remote.host} profile=${remote.profileName}`,
    `user=${remote.username ?? ""}`,
    `port=${remote.port ?? ""}`,
    `known_hosts=${remote.knownHostsPath ?? ""}`,
    `workdirs=${remote.allowedWorkdirs?.join(",") ?? ""}`,
    `sudo=${remote.sudoPolicy ?? ""}`,
  ].join(" ");
}
