import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { buildReactToolRegistry } from "../../../src/react/index.js";
import { createSearchFilesTool } from "../../../src/react/tools/index.js";

describe("React tool catalog", () => {
  it("does not expose pi-coding-agent authority names", () => {
    const tools = buildReactToolRegistry(stubCatalogInput());

    expect(tools.map((tool) => tool.name)).not.toContain("bash");
    expect(tools.map((tool) => tool.name)).not.toContain("write");
    expect(tools.map((tool) => tool.name)).not.toContain("edit");
  });

  it("marks mutating and executing tools as gated", () => {
    const tools = buildReactToolRegistry(stubCatalogInput());
    const gatedTools = tools.filter((tool) =>
      ["linuxagent_execute_command", "apply_file_patch", "run_ssh_command"].includes(tool.name),
    );

    expect(gatedTools).toHaveLength(3);
    expect(gatedTools.every((tool) => tool.linuxAgent.requiresGate)).toBe(true);
  });

  it("routes SSH commands through LinuxAgentToolGate before execution", async () => {
    const gateCalls: unknown[] = [];
    let sshCalls = 0;
    const tools = buildReactToolRegistry({
      ...stubCatalogInput(),
      gate: {
        beforeToolCall: async (context) => {
          gateCalls.push(context);
          return undefined;
        },
      },
      ssh: {
        execute: async () => {
          sshCalls += 1;
          return {
            profileName: "prod-web",
            host: "192.0.2.10",
            port: 22,
            username: "operator",
            command: "uptime",
            argv: ["ssh", "operator@192.0.2.10", "uptime"],
            exitCode: 0,
            stdout: "up\n",
            stderr: "",
            timedOut: false,
          };
        },
      },
    });

    await tools
      .find((tool) => tool.name === "run_ssh_command")
      ?.execute("ssh-call-1", {
        profile: remoteProfile(),
        command: "uptime",
        timeoutMs: 1000,
      });

    expect(sshCalls).toBe(1);
    expect(gateCalls).toEqual([
      {
        toolCallId: "ssh-call-1",
        args: {
          argv: [
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
            "22",
            "operator@192.0.2.10",
            "uptime",
          ],
          remote: {
            type: "ssh",
            host: "192.0.2.10",
            profileName: "prod-web",
            username: "operator",
            port: 22,
            knownHostsPath: "/home/operator/.ssh/known_hosts",
            allowedWorkdirs: ["/var/log"],
            sudoPolicy: "none",
          },
        },
      },
    ]);
  });

  it("does not execute SSH when LinuxAgentToolGate blocks", async () => {
    let sshCalls = 0;
    const tools = buildReactToolRegistry({
      ...stubCatalogInput(),
      gate: {
        beforeToolCall: async () => ({ block: true, reason: "blocked by policy" }),
      },
      ssh: {
        execute: async () => {
          sshCalls += 1;
          throw new Error("ssh executor must not run");
        },
      },
    });

    const result = await tools
      .find((tool) => tool.name === "run_ssh_command")
      ?.execute("ssh-call-1", {
        profile: remoteProfile(),
        command: "uptime",
      });

    expect(sshCalls).toBe(0);
    expect(result?.content[0]?.text).toBe("blocked: blocked by policy");
    expect(result?.terminate).toBe(true);
  });

  it("search_files treats regex characters as literal text", async () => {
    const root = await mkdtemp(join(tmpdir(), "linuxagent-react-tools-"));
    await writeFile(join(root, "notes.txt"), "literal a.*b\nregex axxb\n", "utf8");
    const tool = createSearchFilesTool({ allowedRoots: [root], maxMatches: 10 });

    const result = await tool.execute("call-1", { root, pattern: "a.*b", maxMatches: 10 });

    expect(result.content[0]?.text).toContain("notes.txt:1:literal a.*b");
    expect(result.content[0]?.text).not.toContain("regex axxb");
  });

  it("read-only tools return structured errors for paths outside allowed roots", async () => {
    const allowed = await mkdtemp(join(tmpdir(), "linuxagent-react-tools-allowed-"));
    const outside = await mkdtemp(join(tmpdir(), "linuxagent-react-tools-outside-"));
    await mkdir(join(allowed, "nested"));
    await writeFile(join(outside, "secret.txt"), "secret\n", "utf8");
    const tools = buildReactToolRegistry({
      ...stubCatalogInput(),
      workspace: { allowedRoots: [allowed] },
    });

    const readFile = tools.find((tool) => tool.name === "read_file");
    const result = await readFile?.execute("call-1", { path: join(outside, "secret.txt") });

    expect(result).toMatchObject({
      content: [{ type: "text", text: expect.stringContaining("ok=false") }],
      details: {
        ok: false,
        error: expect.stringContaining("path outside allowed roots"),
      },
      terminate: true,
    });
  });

  it("redacts and bounds read-only tool previews", async () => {
    const root = await mkdtemp(join(tmpdir(), "linuxagent-react-tools-redact-"));
    await writeFile(
      join(root, "secret.txt"),
      `Authorization: Bearer secret-token-value\n${"visible ".repeat(20)}\n`,
      "utf8",
    );
    const tools = buildReactToolRegistry({
      ...stubCatalogInput(),
      workspace: { allowedRoots: [root], maxPreviewChars: 40 },
    });

    const readFile = tools.find((tool) => tool.name === "read_file");
    const result = await readFile?.execute("call-1", {
      path: join(root, "secret.txt"),
      limit: 10,
    });

    expect(result?.content[0]?.text).toContain("[REDACTED]");
    expect(result?.content[0]?.text).not.toContain("secret-token-value");
    expect(result?.content[0]?.text).toContain("[TRUNCATED]");
    expect(result?.details).toMatchObject({
      ok: true,
      redacted: true,
      truncated: true,
    });
  });
});

function stubCatalogInput(): Parameters<typeof buildReactToolRegistry>[0] {
  return {
    gate: {
      beforeToolCall: async () => undefined,
    },
    executor: {
      execute: async () => ({
        enforced: false,
        runner: "noop",
        exitCode: 0,
        stdout: "",
        stderr: "",
        timedOut: false,
        metadata: {},
      }),
    },
    sandbox: { profile: "noop", timeoutMs: 1000 },
    workspace: { allowedRoots: [process.cwd()] },
    filePatch: {
      pathPolicy: { allowedRoots: [process.cwd()] },
      approval: { approvePatch: async () => "deny" },
      audit: { append: async () => undefined },
    },
    ssh: {
      execute: async () => ({
        profileName: "dev",
        host: "127.0.0.1",
        port: 22,
        username: "operator",
        command: "uptime",
        argv: ["ssh", "operator@127.0.0.1", "uptime"],
        exitCode: 0,
        stdout: "",
        stderr: "",
        timedOut: false,
      }),
    },
  };
}

function remoteProfile() {
  return {
    name: "prod-web",
    host: "192.0.2.10",
    port: 22,
    username: "operator",
    keyPath: "/home/operator/.ssh/id_ed25519",
    knownHostsPath: "/home/operator/.ssh/known_hosts",
    allowedWorkdirs: ["/var/log"],
    sudoPolicy: "none" as const,
  };
}
