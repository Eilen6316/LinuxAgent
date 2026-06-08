import { spawn } from "node:child_process";
import type { SandboxExecutionResult, SandboxSpec } from "./models.js";
import type { SandboxRunner } from "./runner.js";

export class NoopSandboxRunner implements SandboxRunner {
  readonly name = "noop";

  canEnforce(profile: SandboxSpec["profile"]): boolean {
    return profile === "noop" || profile === "privileged_passthrough";
  }

  async execute(
    argv: readonly string[],
    spec: SandboxSpec,
    signal?: AbortSignal,
  ): Promise<SandboxExecutionResult> {
    if (!this.canEnforce(spec.profile)) {
      throw new Error(`noop runner cannot enforce ${spec.profile}`);
    }
    const [file, ...args] = argv;
    if (!file) throw new Error("argv[0] must be non-empty");
    return await new Promise((resolve, reject) => {
      const child = spawn(file, args, {
        cwd: spec.cwd,
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
        signal,
      });
      let stdout = "";
      let stderr = "";
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (chunk: string) => {
        stdout += chunk;
      });
      child.stderr.on("data", (chunk: string) => {
        stderr += chunk;
      });
      child.on("error", reject);
      child.on("close", (exitCode) => {
        resolve({
          enforced: false,
          runner: this.name,
          exitCode,
          stdout,
          stderr,
          timedOut: false,
          metadata: { profile: spec.profile },
        });
      });
    });
  }
}
