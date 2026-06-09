import { describe, expect, it } from "vitest";
import {
  formatSummary,
  runAuditParity,
  runFilePatchParity,
  runHarnessParity,
  runHitlParity,
  runOutputRedactionParity,
  runRedTeamParity,
  runSandboxParity,
  runSshParity,
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

  it("checks file patch transaction and rollback behavior", async () => {
    await expect(runFilePatchParity()).resolves.toEqual({
      suite: "file-patch",
      passed: 2,
      total: 2,
      failures: [],
    });
  });

  it("checks HITL session permission parity", async () => {
    await expect(runHitlParity()).resolves.toEqual({
      suite: "hitl",
      passed: 3,
      total: 3,
      failures: [],
    });
  });

  it("checks SSH unknown-host rejection boundary", async () => {
    await expect(runSshParity()).resolves.toEqual({
      suite: "ssh",
      passed: 2,
      total: 2,
      failures: [],
    });
  });

  it("checks harness fixture index parity", () => {
    expect(runHarnessParity()).toEqual({
      suite: "harness",
      passed: 8,
      total: 8,
      failures: [],
    });
  });

  it("checks red-team policy parity", async () => {
    await expect(runRedTeamParity()).resolves.toEqual({
      suite: "red-team",
      passed: 6,
      total: 6,
      failures: [],
    });
  });
});
