import type { SandboxExecutionResult, SandboxSpec } from "./models.js";

export interface SandboxRunner {
  readonly name: string;
  execute(
    argv: readonly string[],
    spec: SandboxSpec,
    signal?: AbortSignal,
  ): Promise<SandboxExecutionResult>;
  canEnforce(profile: SandboxSpec["profile"]): boolean;
}
