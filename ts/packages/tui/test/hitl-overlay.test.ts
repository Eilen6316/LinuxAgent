import { describe, expect, it } from "vitest";

import { LinuxAgentEventRenderer } from "../src/event-renderer.js";
import { renderHitlOverlay } from "../src/hitl-overlay.js";

describe("HITL overlay", () => {
  it("renders command review details and keyboard choices", () => {
    const text = renderHitlOverlay({
      requestId: "req-1",
      argv: ["uname", "-a"],
      goal: "check kernel",
      purpose: "inspect host kernel version",
      policy: {
        level: "CONFIRM",
        reason: "LLM-generated command",
        riskScore: 30,
        capabilities: ["llm.generated"],
        matchedRules: ["LLM_FIRST_RUN"],
        neverWhitelist: false,
      },
      sandbox: { profile: "noop", runner: "noop", enforced: false },
    }).join("\n");

    expect(text).toContain("Approval req-1");
    expect(text).toContain("command: uname -a");
    expect(text).toContain("goal: check kernel");
    expect(text).toContain("purpose: inspect host kernel version");
    expect(text).toContain("policy: CONFIRM risk=30");
    expect(text).toContain("matched_rules: LLM_FIRST_RUN");
    expect(text).toContain("sandbox: profile=noop runner=noop enforced=false");
    expect(text).toContain("[y] Yes");
    expect(text).toContain("[a] Yes, don't ask again");
    expect(text).toContain("[n] No");
  });

  it("deduplicates repeated pending confirmations by request id", () => {
    const renderer = new LinuxAgentEventRenderer();
    const request = {
      requestId: "req-1",
      argv: ["uname", "-a"],
      goal: "check kernel",
      purpose: "inspect host",
      policy: {
        level: "CONFIRM" as const,
        reason: "LLM-generated command",
        riskScore: 30,
        capabilities: ["llm.generated"],
        matchedRules: ["LLM_FIRST_RUN"],
        neverWhitelist: false,
      },
      sandbox: { profile: "noop", runner: "noop", enforced: false },
    };

    renderer.apply({ type: "hitl_request", request });
    renderer.apply({ type: "hitl_request", request });

    const text = renderer.render(100).join("\n");

    expect(text.match(/Approval req-1/g)).toHaveLength(1);
  });
});
