import { readFileSync } from "node:fs";
import { Value } from "typebox/value";
import { describe, expect, it } from "vitest";
import { PolicyDecisionSchema } from "../src/policy-decision.js";

describe("policy fixture contract", () => {
  it("loads Python-exported policy fixtures", () => {
    const file = new URL("../../../parity/fixtures/command-policy.jsonl", import.meta.url);
    const lines = readFileSync(file, "utf8").trim().split("\n");

    expect(lines.length).toBeGreaterThan(0);
    for (const line of lines) {
      const record = JSON.parse(line);
      expect(record.case_id).toEqual(expect.any(String));
      expect(Array.isArray(record.input.argv)).toBe(true);
      expect(Value.Check(PolicyDecisionSchema, record.expected)).toBe(true);
    }
  });
});
