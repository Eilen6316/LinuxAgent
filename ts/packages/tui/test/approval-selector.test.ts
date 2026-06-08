import { describe, expect, it } from "vitest";
import type { PolicyDecision } from "../../contracts/src/index.js";

import { approvalOptions } from "../src/approval-selector.js";

describe("approvalOptions", () => {
  it("offers exactly yes, yes-dont-ask-again, and no for whitelistable decisions", () => {
    expect(approvalOptions(decision(false)).map((option) => option.label)).toEqual([
      "Yes",
      "Yes, don't ask again",
      "No",
    ]);
  });

  it("hides yes-dont-ask-again for never-whitelist decisions", () => {
    expect(approvalOptions(decision(true)).map((option) => option.label)).toEqual(["Yes", "No"]);
  });
});

function decision(neverWhitelist: boolean): PolicyDecision {
  return {
    level: "CONFIRM",
    reason: "review",
    riskScore: 30,
    capabilities: [],
    matchedRules: [],
    neverWhitelist,
  };
}
