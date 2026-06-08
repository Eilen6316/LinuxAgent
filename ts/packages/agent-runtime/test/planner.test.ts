import { describe, expect, it } from "vitest";

import { CommandPlanner, type PlannerModel } from "../src/planner.js";

const modelReturning = (text: string): PlannerModel => ({
  complete: async () => text,
});

describe("CommandPlanner", () => {
  it("returns a command plan for valid model JSON", async () => {
    const planner = new CommandPlanner(
      modelReturning(
        JSON.stringify({
          version: 1,
          summary: "inspect kernel",
          steps: [
            {
              id: "s1",
              argv: ["uname", "-a"],
              source: "llm",
              reason: "inspect kernel version",
            },
          ],
        }),
      ),
    );

    await expect(planner.plan("check kernel")).resolves.toMatchObject({
      ok: true,
      plan: {
        version: 1,
        steps: [{ argv: ["uname", "-a"] }],
      },
    });
  });

  it("rejects invalid JSON before policy or execution", async () => {
    const planner = new CommandPlanner(modelReturning("{not json"));

    await expect(planner.plan("check kernel")).resolves.toMatchObject({
      ok: false,
      error: "invalid_json",
    });
  });

  it("rejects schema-invalid plans before policy or execution", async () => {
    const planner = new CommandPlanner(
      modelReturning(JSON.stringify({ version: 1, summary: "missing steps" })),
    );

    await expect(planner.plan("check kernel")).resolves.toMatchObject({
      ok: false,
      error: "schema_invalid",
    });
  });
});
