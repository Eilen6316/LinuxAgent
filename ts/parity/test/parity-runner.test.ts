import { describe, expect, it } from "vitest";
import { formatSummary } from "../src/parity-runner.js";

describe("parity report formatting", () => {
  it("formats pass counts", () => {
    expect(formatSummary({ suite: "policy", passed: 7, total: 7, failures: [] })).toBe(
      "policy parity: PASS 7/7",
    );
  });

  it("formats fail counts", () => {
    expect(formatSummary({ suite: "policy", passed: 6, total: 7, failures: ["case"] })).toBe(
      "policy parity: FAIL 6/7",
    );
  });
});
