import { spawn } from "node:child_process";

import { guardRemoteCommand, type RemoteCommandGuardResult } from "./remote-command.js";
import { type RemoteProfile, validateRemoteProfile } from "./remote-profile.js";

export interface SshProcessOptions {
  timeoutMs: number;
  signal?: AbortSignal;
}

export interface SshProcessResult {
  exitCode: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
}

export interface SshProcessTransport {
  run(argv: readonly string[], options: SshProcessOptions): Promise<SshProcessResult>;
}

export interface OpenSshExecuteInput {
  profile: RemoteProfile;
  command: string;
  timeoutMs: number;
  signal?: AbortSignal;
}

export interface OpenSshExecutionResult extends SshProcessResult {
  profileName: string;
  host: string;
  port: number;
  username: string;
  command: string;
  argv: readonly string[];
}

export class RemoteCommandBlockedError extends Error {
  readonly guard: RemoteCommandGuardResult;

  constructor(guard: RemoteCommandGuardResult) {
    super(guard.reason ?? "remote command is blocked");
    this.name = "RemoteCommandBlockedError";
    this.guard = guard;
  }
}

export class RemoteCommandConfirmationRequiredError extends Error {
  readonly guard: RemoteCommandGuardResult;

  constructor(guard: RemoteCommandGuardResult) {
    super(guard.reason ?? "remote command requires confirmation");
    this.name = "RemoteCommandConfirmationRequiredError";
    this.guard = guard;
  }
}

export function buildOpenSshArgv(profile: RemoteProfile, command: string): readonly string[] {
  const validated = validateRemoteProfile(profile);
  return [
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "StrictHostKeyChecking=yes",
    "-o",
    `UserKnownHostsFile=${validated.knownHostsPath}`,
    "-i",
    validated.keyPath,
    "-p",
    String(validated.port),
    `${validated.username}@${validated.host}`,
    command,
  ];
}

export class OpenSshManager {
  constructor(private readonly transport: SshProcessTransport) {}

  async execute(input: OpenSshExecuteInput): Promise<OpenSshExecutionResult> {
    const profile = validateRemoteProfile(input.profile);
    const guard = guardRemoteCommand(input.command);
    if (guard.level === "BLOCK") {
      throw new RemoteCommandBlockedError(guard);
    }
    if (guard.level === "CONFIRM") {
      throw new RemoteCommandConfirmationRequiredError(guard);
    }
    const argv = buildOpenSshArgv(profile, input.command);
    const options: SshProcessOptions =
      input.signal === undefined
        ? { timeoutMs: input.timeoutMs }
        : { timeoutMs: input.timeoutMs, signal: input.signal };
    const result = await this.transport.run(argv, options);
    return {
      ...result,
      profileName: profile.name,
      host: profile.host,
      port: profile.port,
      username: profile.username,
      command: input.command,
      argv,
    };
  }
}

export class SpawnSshProcessTransport implements SshProcessTransport {
  async run(argv: readonly string[], options: SshProcessOptions): Promise<SshProcessResult> {
    const [file, ...args] = argv;
    if (!file) throw new Error("ssh argv must contain at least one token");
    return await new Promise((resolve, reject) => {
      let timedOut = false;
      const child = spawn(file, args, {
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
        signal: options.signal,
      });
      const timeout = setTimeout(() => {
        timedOut = true;
        child.kill("SIGTERM");
      }, options.timeoutMs);
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
      child.on("error", (error) => {
        clearTimeout(timeout);
        reject(error);
      });
      child.on("close", (exitCode) => {
        clearTimeout(timeout);
        resolve({ exitCode, stdout, stderr, timedOut });
      });
    });
  }
}
