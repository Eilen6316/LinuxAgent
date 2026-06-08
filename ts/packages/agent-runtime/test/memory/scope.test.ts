import { describe, expect, it } from "vitest";

import { type MemoryScope, memoryScopeKey, sameMemoryScope } from "../../src/memory/scope.js";

describe("memory scope", () => {
  it("builds stable keys from namespace, project, host, repo, and workdir", () => {
    const scope: MemoryScope = {
      namespace: "default",
      projectId: "ops-api",
      host: "prod-host",
      repo: "/srv/ops/api",
      workdir: "/srv/ops/api",
    };

    expect(memoryScopeKey(scope)).toBe("default|ops-api|prod-host|/srv/ops/api|/srv/ops/api");
  });

  it("keeps memory from repo A out of repo B", () => {
    const repoA: MemoryScope = {
      namespace: "default",
      projectId: "ops",
      host: "host-a",
      repo: "/srv/ops/a",
      workdir: "/srv/ops/a",
    };
    const repoB: MemoryScope = {
      namespace: "default",
      projectId: "ops",
      host: "host-a",
      repo: "/srv/ops/b",
      workdir: "/srv/ops/b",
    };

    expect(sameMemoryScope(repoA, repoB)).toBe(false);
  });

  it("normalizes trailing slashes and missing optional fields", () => {
    expect(
      sameMemoryScope(
        { namespace: "default", repo: "/srv/app/", workdir: "/srv/app" },
        { namespace: "default", repo: "/srv/app", workdir: "/srv/app/" },
      ),
    ).toBe(true);
    expect(memoryScopeKey({ namespace: "default" })).toBe("default|-|-|-|-");
  });
});
