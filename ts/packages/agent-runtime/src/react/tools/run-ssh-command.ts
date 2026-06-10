import type { OpenSshExecutionResult, RemoteProfile } from "@linuxagent/ssh";
import { Type } from "typebox";
import type { ReactAgentTool } from "./types.js";

const RemoteProfileParameters = Type.Object({
  name: Type.String(),
  host: Type.String(),
  port: Type.Number(),
  username: Type.String(),
  keyPath: Type.String(),
  knownHostsPath: Type.String(),
  allowedWorkdirs: Type.Array(Type.String()),
  sudoPolicy: Type.Union([Type.Literal("none"), Type.Literal("allowlisted")]),
});

const RunSshCommandParameters = Type.Object({
  profile: RemoteProfileParameters,
  command: Type.String(),
  timeoutMs: Type.Optional(Type.Number()),
});

export interface SshExecutorPort {
  execute(input: {
    profile: RemoteProfile;
    command: string;
    timeoutMs: number;
    signal?: AbortSignal;
  }): Promise<OpenSshExecutionResult>;
}

export function createRunSshCommandTool(executor?: SshExecutorPort): ReactAgentTool {
  return {
    name: "run_ssh_command",
    label: "Run SSH command",
    description: "Run a remote command through LinuxAgent SSH profile and remote command guards.",
    parameters: RunSshCommandParameters,
    executionMode: "sequential",
    linuxAgent: { category: "ssh", requiresGate: true, sandboxProfile: "system_inspect" },
    async execute(_toolCallId, params, signal) {
      if (executor === undefined) throw new Error("ssh tool is not configured");
      const args = params as { profile: RemoteProfile; command: string; timeoutMs?: number };
      const result = await executor.execute({
        profile: args.profile,
        command: args.command,
        timeoutMs: args.timeoutMs ?? 30_000,
        ...(signal ? { signal } : {}),
      });
      return {
        content: [{ type: "text", text: sshResultForModel(result) }],
        details: { result },
      };
    },
  };
}

function sshResultForModel(result: OpenSshExecutionResult): string {
  return [
    `ssh profile=${result.profileName}`,
    `host=${result.host}`,
    `exit_code=${result.exitCode}`,
    `stdout=${result.stdout.trimEnd()}`,
    `stderr=${result.stderr.trimEnd()}`,
  ].join("\n");
}
