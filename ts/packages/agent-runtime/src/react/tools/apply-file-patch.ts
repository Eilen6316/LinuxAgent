import { FilePatchPlanSchema } from "@linuxagent/contracts";
import { Type } from "typebox";
import { type ExecuteFilePatchToolInput, executeFilePatchTool } from "../../file-patch/index.js";
import type { ReactAgentTool } from "./types.js";

export type FilePatchToolPorts = Omit<ExecuteFilePatchToolInput, "args">;

export function createApplyFilePatchTool(ports?: FilePatchToolPorts): ReactAgentTool {
  return {
    name: "apply_file_patch",
    label: "Apply file patch",
    description: "Apply a structured file patch transaction through LinuxAgent approval and audit.",
    parameters: Type.Unsafe(FilePatchPlanSchema),
    executionMode: "sequential",
    linuxAgent: { category: "write", requiresGate: true, sandboxProfile: "workspace_write" },
    async execute(_toolCallId, params) {
      if (ports === undefined) throw new Error("file patch tool is not configured");
      const result = await executeFilePatchTool({ ...ports, args: params });
      return {
        content: [{ type: "text", text: result.modelText }],
        details: { result },
        terminate: !result.executed,
      };
    },
  };
}
