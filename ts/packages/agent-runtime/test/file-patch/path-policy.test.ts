import { mkdir, mkdtemp, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { assertModeSafe, assertPathAllowed } from "../../src/file-patch/path-policy.js";

describe("file patch path policy", () => {
  it("allows paths below configured roots", async () => {
    const root = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    const targetDir = join(root, "workspace");
    await mkdir(targetDir);

    await expect(
      assertPathAllowed(join(targetDir, "app.conf"), { allowedRoots: [targetDir] }),
    ).resolves.toBe(join(targetDir, "app.conf"));
  });

  it("blocks relative traversal outside configured roots", async () => {
    const root = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    const allowed = join(root, "workspace");
    await mkdir(allowed);

    await expect(
      assertPathAllowed(join(allowed, "..", "outside.conf"), { allowedRoots: [allowed] }),
    ).rejects.toThrow("path outside allowed roots");
  });

  it("blocks paths that escape through symlinked parent directories", async () => {
    const root = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    const allowed = join(root, "workspace");
    const outside = join(root, "outside");
    await mkdir(allowed);
    await mkdir(outside);
    await symlink(outside, join(allowed, "link"));

    await expect(
      assertPathAllowed(join(allowed, "link", "secret.conf"), { allowedRoots: [allowed] }),
    ).rejects.toThrow("path outside allowed roots");
  });

  it("blocks NUL bytes in paths", async () => {
    const root = await mkdtemp(join(tmpdir(), "linuxagent-file-patch-"));
    await expect(assertPathAllowed(`${root}/bad\0name`, { allowedRoots: [root] })).rejects.toThrow(
      "path contains NUL byte",
    );
  });

  it("blocks setuid and setgid permission changes", () => {
    expect(() => assertModeSafe("0755")).not.toThrow();
    expect(() => assertModeSafe("4755")).toThrow("setuid/setgid permission changes are blocked");
    expect(() => assertModeSafe("2755")).toThrow("setuid/setgid permission changes are blocked");
  });
});
