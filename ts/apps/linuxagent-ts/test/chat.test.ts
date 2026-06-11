import { describe, expect, it } from "vitest";

import { runChatCommand } from "../src/commands/chat.js";

describe("chat command", () => {
  it("keeps --input on the non-interactive ReAct runtime path", async () => {
    await expect(runChatCommand("check kernel")).resolves.toBe(
      "linuxagent-ts chat: react completed",
    );
  });

  it("runs --input through the ReAct runtime port", async () => {
    const calls: string[] = [];

    const result = await runChatCommand("check kernel", {
      runReactTurn: async (input) => {
        calls.push(input);
        return {
          status: "completed",
          assistantMessage: "Use uname -a.",
          toolResults: [],
        };
      },
    });

    expect(result).toBe("linuxagent-ts chat: react completed");
    expect(calls).toEqual(["check kernel"]);
  });

  it("does not start interactive mode without a TTY", async () => {
    const result = await runChatCommand(undefined, {
      stdin: { isTTY: false },
      stdout: { isTTY: false },
      launchInteractive: async () => "should-not-run",
    });

    expect(result).toBe("linuxagent-ts chat: non_interactive requires --input");
  });

  it("starts the experimental interactive launcher only when stdin and stdout are TTYs", async () => {
    const result = await runChatCommand(undefined, {
      stdin: { isTTY: true },
      stdout: { isTTY: true },
      launchInteractive: async () => "linuxagent-ts chat: interactive experimental",
    });

    expect(result).toBe("linuxagent-ts chat: interactive experimental");
  });
});
