import { describe, expect, it } from "vitest";
import type { LinuxAgentUiEvent } from "../src/event-renderer.js";
import { applyStatusEvent, renderStatusLine } from "../src/status-line.js";

describe("status line", () => {
  it("tracks model, tool, and pending approval activity", () => {
    const events: LinuxAgentUiEvent[] = [
      { type: "model_start", model: "fake-react" },
      { type: "tool_start", toolName: "linuxagent_execute_command", label: "Execute command" },
      {
        type: "hitl_request",
        request: {
          requestId: "req-1",
          argv: ["uname", "-a"],
          goal: "check kernel",
          purpose: "inspect host",
          policy: {
            level: "CONFIRM",
            reason: "LLM-generated command",
            riskScore: 30,
            capabilities: ["llm.generated"],
            matchedRules: ["LLM_FIRST_RUN"],
            neverWhitelist: false,
          },
          sandbox: { profile: "noop", runner: "noop", enforced: false },
        },
      },
    ];

    const state = events.reduce(applyStatusEvent, undefined);

    expect(renderStatusLine(state)).toBe(
      "LinuxAgent TS | model fake-react | tool Execute command | awaiting approval req-1",
    );
  });
});
