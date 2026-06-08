import { describe, expect, it } from "vitest";
import type { RemoteProfile } from "../src/remote-profile.js";
import {
  buildOpenSshArgv,
  OpenSshManager,
  RemoteCommandBlockedError,
  RemoteCommandConfirmationRequiredError,
  type SshProcessTransport,
} from "../src/ssh-manager.js";

const PROFILE: RemoteProfile = {
  name: "prod-web",
  host: "192.0.2.10",
  port: 2222,
  username: "operator",
  keyPath: "/home/operator/.ssh/id_ed25519",
  knownHostsPath: "/home/operator/.ssh/known_hosts",
  allowedWorkdirs: ["/var/log"],
  sudoPolicy: "none",
};

describe("buildOpenSshArgv", () => {
  it("forces known-host rejection through OpenSSH argv", () => {
    expect(buildOpenSshArgv(PROFILE, "uptime")).toEqual([
      "ssh",
      "-o",
      "BatchMode=yes",
      "-o",
      "StrictHostKeyChecking=yes",
      "-o",
      "UserKnownHostsFile=/home/operator/.ssh/known_hosts",
      "-i",
      "/home/operator/.ssh/id_ed25519",
      "-p",
      "2222",
      "operator@192.0.2.10",
      "uptime",
    ]);
  });
});

describe("OpenSshManager", () => {
  it("runs safe remote commands through an argv-only transport", async () => {
    const calls: readonly string[][] = [];
    const transport: SshProcessTransport = {
      async run(argv) {
        (calls as string[][]).push([...argv]);
        return {
          exitCode: 0,
          stdout: "up\n",
          stderr: "",
          timedOut: false,
        };
      },
    };
    const manager = new OpenSshManager(transport);

    const result = await manager.execute({
      profile: PROFILE,
      command: "uptime",
      timeoutMs: 5000,
    });

    expect(calls).toEqual([buildOpenSshArgv(PROFILE, "uptime")]);
    expect(result).toMatchObject({
      profileName: "prod-web",
      host: "192.0.2.10",
      command: "uptime",
      exitCode: 0,
      stdout: "up\n",
      stderr: "",
      timedOut: false,
    });
  });

  it("blocks remote command substitution before transport execution", async () => {
    let invoked = false;
    const manager = new OpenSshManager({
      async run() {
        invoked = true;
        throw new Error("transport must not run");
      },
    });

    await expect(
      manager.execute({
        profile: PROFILE,
        command: "echo $(cat /etc/shadow)",
        timeoutMs: 5000,
      }),
    ).rejects.toBeInstanceOf(RemoteCommandBlockedError);
    expect(invoked).toBe(false);
  });

  it("requires explicit confirmation for remote shell metacharacters", async () => {
    let invoked = false;
    const manager = new OpenSshManager({
      async run() {
        invoked = true;
        throw new Error("transport must not run");
      },
    });

    await expect(
      manager.execute({
        profile: PROFILE,
        command: "journalctl | tail",
        timeoutMs: 5000,
      }),
    ).rejects.toBeInstanceOf(RemoteCommandConfirmationRequiredError);
    expect(invoked).toBe(false);
  });
});
