import { Type } from "typebox";
import type { ReactAgentTool } from "./types.js";
import { listWorkspaceDir, type WorkspaceToolConfig } from "./workspace.js";
import { workspaceToolResult } from "./workspace-result.js";

const ListDirParameters = Type.Object({
  path: Type.Optional(Type.String()),
  limit: Type.Optional(Type.Number()),
});

export function createListDirTool(config: WorkspaceToolConfig): ReactAgentTool {
  return {
    name: "list_dir",
    label: "List directory",
    description: "List a bounded directory window under allowed workspace roots.",
    parameters: ListDirParameters,
    linuxAgent: { category: "read", requiresGate: false, sandboxProfile: "read_only" },
    async execute(_toolCallId, params) {
      const args = params as { path?: string; limit?: number };
      return await workspaceToolResult(config, async () => {
        const entries = await listWorkspaceDir(args.path ?? ".", config, args.limit);
        return { text: entries.join("\n"), details: { entries } };
      });
    },
  };
}
