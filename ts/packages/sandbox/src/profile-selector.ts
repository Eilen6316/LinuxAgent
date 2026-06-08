import type { SandboxProfile, SandboxSpec } from "./models.js";
import type { SandboxRunner } from "./runner.js";

export class SandboxUnavailableError extends Error {}

export function selectSandboxRunner(
  runners: readonly SandboxRunner[],
  spec: SandboxSpec,
): SandboxRunner {
  const runner = runners.find((candidate) => candidate.canEnforce(spec.profile));
  if (!runner) throw new SandboxUnavailableError(`no sandbox runner can enforce ${spec.profile}`);
  return runner;
}

export function requiresEnforcement(profile: SandboxProfile): boolean {
  return profile === "read_only" || profile === "workspace_write" || profile === "system_inspect";
}
