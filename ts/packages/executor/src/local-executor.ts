import type {
  SandboxExecutionResult,
  SandboxRunner,
  SandboxSpec,
} from "../../sandbox/src/index.js";
import { SandboxUnavailableError, selectSandboxRunner } from "../../sandbox/src/index.js";

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
