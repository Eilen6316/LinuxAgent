import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { runReactTurnParity } from "../src/react-turn-runner.js";

describe("ReAct turn parity runner", () => {
  it("checks deterministic P0 ReAct turn fixtures", async () => {
    await expect(runReactTurnParity()).resolves.toEqual({
      suite: "react-turn",
      passed: 9,
      total: 9,
      failures: [],
    });
  });

  it("reports actionable fixture ids on mismatch", async () => {
    const dir = await mkdtemp(join(tmpdir(), "linuxagent-react-turn-fixtures-"));
    const path = join(dir, "react-turns.jsonl");
    await writeFile(
      path,
      `${JSON.stringify({
        schemaVersion: 1,
        caseId: "bad-status",
        userInput: "hello",
        modelMessages: [{ type: "final", text: "hello" }],
        expected: {
          status: "blocked",
          approvalRequests: 0,
          executorCalls: [],
          auditEvents: [],
        },
      })}\n`,
      "utf8",
    );

    const summary = await runReactTurnParity(path);

    expect(summary.failures[0]).toContain("bad-status:");
    expect(summary.failures[0]).toContain("expected status blocked, got completed");
  });
});
