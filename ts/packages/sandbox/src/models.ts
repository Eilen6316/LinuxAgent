export type SandboxProfile =
  | "noop"
  | "read_only"
  | "workspace_write"
  | "system_inspect"
  | "privileged_passthrough";

export interface SandboxSpec {
  profile: SandboxProfile;
  timeoutMs: number;
  cwd?: string;
}

export interface SandboxExecutionResult {
  enforced: boolean;
  runner: string;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
  metadata: Record<string, unknown>;
}
