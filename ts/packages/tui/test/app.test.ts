import { describe, expect, it } from "vitest";

import { type ChatTurnRunner, LinuxAgentChatSession } from "../src/app.js";

describe("LinuxAgentChatSession", () => {
  it("passes normal chat input to the runtime", async () => {
    const calls: string[] = [];
    const runner: ChatTurnRunner = {
      runTurn: async (input) => {
        calls.push(input);
        return { kind: "direct_answer", answer: "ok" };
      },
    };
    const session = new LinuxAgentChatSession(runner);

    const result = await session.handleInput("check kernel");

    expect(calls).toEqual(["check kernel"]);
    expect(result).toEqual({ kind: "runtime", result: { kind: "direct_answer", answer: "ok" } });
  });

  it("handles slash quit without invoking the runtime", async () => {
    const calls: string[] = [];
    const session = new LinuxAgentChatSession({
      runTurn: async (input) => {
        calls.push(input);
        return { kind: "direct_answer", answer: "unexpected" };
      },
    });

    await expect(session.handleInput("/quit")).resolves.toEqual({ kind: "quit" });
    expect(calls).toHaveLength(0);
  });
});
