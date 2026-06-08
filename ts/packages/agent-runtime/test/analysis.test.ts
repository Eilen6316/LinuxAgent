import { describe, expect, it } from "vitest";

import { afterLinuxAgentToolCall } from "../src/analysis.js";

describe("afterLinuxAgentToolCall", () => {
  it("redacts stdout and stderr before model-facing analysis", async () => {
    const result = await afterLinuxAgentToolCall({
      result: {
        details: {
          stdout: "Authorization: Bearer stdout-secret-token",
          stderr: "sk-1234567890abcdefghijklmnop",
          sandbox: { runner: "noop" },
        },
      },
      isError: false,
    });

    expect(result.details).toMatchObject({
      stdout: "Authorization: [REDACTED]",
      stderr: "[REDACTED]",
      sandbox: { runner: "noop" },
      outputRedaction: {
        stdout: true,
        stderr: true,
      },
    });
    expect(JSON.stringify(result.details)).not.toContain("stdout-secret-token");
    expect(result.isError).toBe(false);
  });

  it("preserves the tool error flag without reinterpreting policy decisions", async () => {
    const result = await afterLinuxAgentToolCall({
      result: {
        details: {
          stdout: "ok",
          stderr: "",
          policy: { level: "BLOCK" },
        },
      },
      isError: true,
    });

    expect(result.isError).toBe(true);
    expect(result.details).toMatchObject({
      policy: { level: "BLOCK" },
      outputRedaction: {
        stdout: false,
        stderr: false,
      },
    });
  });
});
