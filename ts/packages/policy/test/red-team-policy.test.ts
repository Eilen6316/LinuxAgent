import { describe, expect, it } from "vitest";
import { PolicyEngine } from "../src/engine.js";

async function loadEngine(): Promise<PolicyEngine> {
  const config = new URL("../../../../configs/policy.default.yaml", import.meta.url);
  return PolicyEngine.loadFromYaml(config.pathname);
}

describe("red-team policy parity slice", () => {
  it("blocks recursive force deletes of protected system trees", async () => {
    const engine = await loadEngine();
    for (const argv of [
      ["rm", "-rf", "/etc"],
      ["rm", "--recursive", "--force", "/boot"],
    ]) {
      const decision = engine.evaluate(argv, { source: "operator" });
      expect(decision.level, argv.join(" ")).toBe("BLOCK");
      expect(decision.neverWhitelist, argv.join(" ")).toBe(true);
      expect(decision.matchedRules, argv.join(" ")).toContain("PROTECTED_TREE_DELETE");
      expect(decision.capabilities, argv.join(" ")).toContain("filesystem.delete");
    }
  });

  it("blocks dd writes to protected block devices", async () => {
    const engine = await loadEngine();
    const decision = engine.evaluate(["dd", "if=/dev/zero", "of=/dev/sda", "bs=1M"], {
      source: "operator",
    });

    expect(decision.level).toBe("BLOCK");
    expect(decision.neverWhitelist).toBe(true);
    expect(decision.matchedRules).toContain("BLOCK_DEVICE_MUTATE");
    expect(decision.capabilities).toContain("block_device.mutate");
  });
});
