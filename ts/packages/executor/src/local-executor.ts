import type { SandboxExecutionResult, SandboxRunner, SandboxSpec } from "@linuxagent/sandbox";
import { SandboxUnavailableError, selectSandboxRunner } from "@linuxagent/sandbox";

export class LocalExecutor {
  constructor(private readonly runners: readonly SandboxRunner[]) {}

  async execute(
    argv: readonly string[],
    spec: SandboxSpec,
    signal?: AbortSignal,
  ): Promise<SandboxExecutionResult> {
    if (argv.length === 0) throw new Error("argv must contain at least one token");
    const runner = selectSandboxRunner(this.runners, spec);
    const result = await runner.execute(argv, spec, signal);
    if (result.enforced && !runner.canEnforce(spec.profile)) {
      throw new SandboxUnavailableError(
        `runner ${runner.name} reported false enforcement for ${spec.profile}`,
      );
    }
    return result;
  }
}
