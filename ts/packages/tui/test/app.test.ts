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

  it("routes bang-prefixed input to direct command mode", async () => {
    const runtimeCalls: string[] = [];
    const directCalls: string[] = [];
    const session = new LinuxAgentChatSession(
      {
        runTurn: async (input) => {
          runtimeCalls.push(input);
          return { kind: "direct_answer", answer: "unexpected" };
        },
      },
      {
        runDirectCommand: async (command) => {
          directCalls.push(command);
          return {
            executed: true,
            exitCode: 0,
            sandbox: { enforced: false, runner: "noop", timedOut: false, metadata: {} },
            modelText: "ok",
            redacted: false,
            truncated: false,
          };
        },
      },
    );

    const result = await session.handleInput("!uname -a");

    expect(result).toMatchObject({ kind: "direct_command", result: { executed: true } });
    expect(directCalls).toEqual(["uname -a"]);
    expect(runtimeCalls).toHaveLength(0);
  });
});
