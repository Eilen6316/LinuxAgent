import { describe, expect, it } from "vitest";

import { renderConfirmation } from "../src/confirmation-renderer.js";

describe("renderConfirmation", () => {
  it("renders command, policy, sandbox, and whitelist status", () => {
    const text = renderConfirmation({
      argv: ["uname", "-a"],
      policy: {
        level: "CONFIRM",
        reason: "LLM-generated command; first run requires approval",
        riskScore: 30,
        capabilities: ["llm.generated"],
        matchedRules: ["LLM_FIRST_RUN"],
        neverWhitelist: false,
      },
      sandbox: {
        profile: "noop",
        runner: "noop",
        enforced: false,
      },
    });

    expect(text).toContain("argv: uname -a");
    expect(text).toContain("policy: CONFIRM");
    expect(text).toContain("reason: LLM-generated command; first run requires approval");
    expect(text).toContain("capabilities: llm.generated");
    expect(text).toContain("matched_rules: LLM_FIRST_RUN");
    expect(text).toContain("sandbox: profile=noop runner=noop enforced=false");
    expect(text).toContain("never_whitelist: false");
  });
});
