import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { PolicyEngine } from "../src/engine.js";

interface PolicyFixtureRecord {
  case_id: string;
  input: {
    argv: string[];
    source: "llm" | "operator" | "runbook";
  };
  expected: {
    level: "SAFE" | "CONFIRM" | "BLOCK";
    neverWhitelist: boolean;
    matchedRules: string[];
    capabilities: string[];
  };
}

describe("policy parity", () => {
  it("matches Python-exported policy fixture decisions exactly for selected gate fields", async () => {
    const config = new URL("../../../../configs/policy.default.yaml", import.meta.url);
    const engine = await PolicyEngine.loadFromYaml(config.pathname);
    const file = new URL("../../../parity/fixtures/command-policy.jsonl", import.meta.url);
    const lines = readFileSync(file, "utf8").trim().split("\n");

    for (const line of lines) {
      const record = JSON.parse(line) as PolicyFixtureRecord;
      const actual = engine.evaluate(record.input.argv, { source: record.input.source });
      expect(actual.level, record.case_id).toBe(record.expected.level);
      expect(actual.neverWhitelist, record.case_id).toBe(record.expected.neverWhitelist);
      expect(new Set(actual.matchedRules), record.case_id).toEqual(
        new Set(record.expected.matchedRules),
      );
      expect(new Set(actual.capabilities), record.case_id).toEqual(
        new Set(record.expected.capabilities),
      );
    }
  });
});
