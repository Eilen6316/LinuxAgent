import { describe, expect, it } from "vitest";
import { LinuxAgentRuntime } from "../src/linuxagent-agent.js";
import { CommandPlanner, type PlannerModel } from "../src/planner.js";
import type { LinuxAgentToolGate } from "../src/tool-gate.js";

const model: PlannerModel = {
  complete: async () => JSON.stringify({ version: 1, summary: "noop", steps: [] }),
};

const commandTool = {
  name: "execute_command",
};

const gate = {
  beforeToolCall: async () => undefined,
} satisfies Pick<LinuxAgentToolGate, "beforeToolCall">;

describe("LinuxAgentRuntime", () => {
  it("requires a tool gate before exposing command tools", () => {
    expect(
      () =>
        new LinuxAgentRuntime({
          planner: new CommandPlanner(model),
          commandTool,
        }),
    ).toThrow("toolGate is required");
  });

  it("exposes executing tools in sequential mode", () => {
    const runtime = new LinuxAgentRuntime({
      planner: new CommandPlanner(model),
      toolGate: gate,
      commandTool,
    });

    expect(runtime.tools()).toHaveLength(1);
    expect(runtime.tools()[0]).toMatchObject({
      name: "execute_command",
      executionMode: "sequential",
    });
  });
});
