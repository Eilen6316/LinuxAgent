import { describe, expect, it } from "vitest";
import {
  formatSummary,
  runAuditParity,
  runOutputRedactionParity,
  runSandboxParity,
} from "../src/parity-runner.js";

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

  it("checks audit verifier tamper detection", async () => {
    await expect(runAuditParity()).resolves.toEqual({
      suite: "audit",
      passed: 2,
      total: 2,
      failures: [],
    });
  });

  it("checks sandbox fail-closed behavior", async () => {
    await expect(runSandboxParity()).resolves.toEqual({
      suite: "sandbox",
      passed: 2,
      total: 2,
      failures: [],
    });
  });

  it("checks output redaction behavior", () => {
    expect(runOutputRedactionParity()).toEqual({
      suite: "output-redaction",
      passed: 2,
      total: 2,
      failures: [],
    });
  });
});
