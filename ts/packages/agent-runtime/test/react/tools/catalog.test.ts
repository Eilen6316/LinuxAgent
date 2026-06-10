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

  it("search_files treats regex characters as literal text", async () => {
    const root = await mkdtemp(join(tmpdir(), "linuxagent-react-tools-"));
    await writeFile(join(root, "notes.txt"), "literal a.*b\nregex axxb\n", "utf8");
    const tool = createSearchFilesTool({ allowedRoots: [root], maxMatches: 10 });

    const result = await tool.execute("call-1", { root, pattern: "a.*b", maxMatches: 10 });

    expect(result.content[0]?.text).toContain("notes.txt:1:literal a.*b");
    expect(result.content[0]?.text).not.toContain("regex axxb");
  });

  it("read-only tools reject paths outside allowed roots", async () => {
    const allowed = await mkdtemp(join(tmpdir(), "linuxagent-react-tools-allowed-"));
    const outside = await mkdtemp(join(tmpdir(), "linuxagent-react-tools-outside-"));
    await mkdir(join(allowed, "nested"));
    await writeFile(join(outside, "secret.txt"), "secret\n", "utf8");
    const tools = buildReactToolRegistry({
      ...stubCatalogInput(),
      workspace: { allowedRoots: [allowed] },
    });

    const readFile = tools.find((tool) => tool.name === "read_file");
    await expect(
      readFile?.execute("call-1", { path: join(outside, "secret.txt") }),
    ).rejects.toThrow("path outside allowed roots");
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
