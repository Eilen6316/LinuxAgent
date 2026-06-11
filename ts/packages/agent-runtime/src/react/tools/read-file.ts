import { Type } from "typebox";
import type { ReactAgentTool } from "./types.js";
import { readWorkspaceFile, type WorkspaceToolConfig } from "./workspace.js";
import { workspaceToolResult } from "./workspace-result.js";

const ReadFileParameters = Type.Object({
  path: Type.String(),
  offset: Type.Optional(Type.Number()),
  limit: Type.Optional(Type.Number()),
});

export function createReadFileTool(config: WorkspaceToolConfig): ReactAgentTool {
  return {
    name: "read_file",
    label: "Read file",
    description: "Read a bounded text window from an allowed workspace file.",
    parameters: ReadFileParameters,
    linuxAgent: { category: "read", requiresGate: false, sandboxProfile: "read_only" },
    async execute(_toolCallId, params) {
      const args = params as { path: string; offset?: number; limit?: number };
      return await workspaceToolResult(config, async () => {
        const text = await readWorkspaceFile(args.path, config, args.offset, args.limit);
        return { text, details: { path: args.path } };
      });
    },
  };
}
