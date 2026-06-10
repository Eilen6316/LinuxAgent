import { describe, expect, it } from "vitest";

import { LinuxAgentEventRenderer } from "../src/event-renderer.js";
import { renderTaskPlan } from "../src/task-plan.js";

describe("task plan rendering", () => {
  it("renders task status without layout shifts", () => {
    expect(
      renderTaskPlan([
        { id: "inspect", title: "Inspect kernel", status: "running" },
        { id: "summarize", title: "Summarize result", status: "pending" },
      ]),
    ).toEqual(["Plan", "> Inspect kernel", "- Summarize result"]);
  });

  it("keeps the plan visible while command activity updates", () => {
    const renderer = new LinuxAgentEventRenderer();
    renderer.apply({
      type: "task_plan_update",
      tasks: [
        { id: "inspect", title: "Inspect kernel", status: "running" },
        { id: "summarize", title: "Summarize result", status: "pending" },
      ],
    });
    renderer.apply({
      type: "tool_start",
      toolName: "linuxagent_execute_command",
      label: "Execute command",
      argv: ["uname", "-a"],
    });

    const text = renderer.render(100).join("\n");

    expect(text).toContain("Plan");
    expect(text).toContain("> Inspect kernel");
    expect(text).toContain("- Summarize result");
    expect(text).toContain("Activity");
    expect(text).toContain("Execute command");
    expect(text).toContain("uname -a");
  });
});
