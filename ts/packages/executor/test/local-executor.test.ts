import { describe, expect, it } from "vitest";
import { NoopSandboxRunner } from "../../sandbox/src/index.js";
import { LocalExecutor } from "../src/local-executor.js";

describe("LocalExecutor", () => {
  it("fails closed when no runner can enforce a safe profile", async () => {
    const executor = new LocalExecutor([new NoopSandboxRunner()]);

    await expect(
      executor.execute(["printf", "ok"], { profile: "read_only", timeoutMs: 1000 }),
    ).rejects.toThrow("no sandbox runner can enforce read_only");
  });

  it("does not claim noop execution is enforced", async () => {
    const executor = new LocalExecutor([new NoopSandboxRunner()]);

    const result = await executor.execute(["printf", "|"], { profile: "noop", timeoutMs: 1000 });

    expect(result.enforced).toBe(false);
    expect(result.stdout).toBe("|");
  });
});
