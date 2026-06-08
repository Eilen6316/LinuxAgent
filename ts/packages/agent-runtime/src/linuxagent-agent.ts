import type { CommandPlanner } from "./planner.js";
import type { LinuxAgentToolGate } from "./tool-gate.js";

export type LinuxAgentToolExecutionMode = "sequential" | "parallel";

export interface LinuxAgentRuntimeTool {
  name: string;
  executionMode?: LinuxAgentToolExecutionMode;
}

export interface LinuxAgentRuntimeDeps {
  planner: CommandPlanner;
  toolGate?: Pick<LinuxAgentToolGate, "beforeToolCall">;
  commandTool: LinuxAgentRuntimeTool;
}

export class LinuxAgentRuntime {
  private readonly deps: Required<LinuxAgentRuntimeDeps>;

  constructor(deps: LinuxAgentRuntimeDeps) {
    if (!deps.toolGate) {
      throw new Error("toolGate is required before exposing command tools");
    }
    this.deps = { ...deps, toolGate: deps.toolGate };
  }

  tools(): LinuxAgentRuntimeTool[] {
    return [{ ...this.deps.commandTool, executionMode: "sequential" }];
  }

  planner(): CommandPlanner {
    return this.deps.planner;
  }

  toolGate(): Pick<LinuxAgentToolGate, "beforeToolCall"> {
    return this.deps.toolGate;
  }
}
