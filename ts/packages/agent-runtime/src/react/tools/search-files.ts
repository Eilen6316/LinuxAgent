import { Type } from "typebox";
import type { ReactAgentTool } from "./types.js";
import { searchWorkspaceFiles, type WorkspaceToolConfig } from "./workspace.js";
import { workspaceToolResult } from "./workspace-result.js";

const SearchFilesParameters = Type.Object({
  pattern: Type.String(),
  root: Type.Optional(Type.String()),
  maxMatches: Type.Optional(Type.Number()),
});

export function createSearchFilesTool(config: WorkspaceToolConfig): ReactAgentTool {
  return {
    name: "search_files",
    label: "Search files",
    description: "Search allowed workspace files for literal text.",
    parameters: SearchFilesParameters,
    linuxAgent: { category: "read", requiresGate: false, sandboxProfile: "read_only" },
    async execute(_toolCallId, params) {
      const args = params as { pattern: string; root?: string; maxMatches?: number };
      return await workspaceToolResult(config, async () => {
        const matches = await searchWorkspaceFiles(
          args.root ?? ".",
          args.pattern,
          config,
          args.maxMatches,
        );
        return { text: matches.join("\n"), details: { matches } };
      });
    },
  };
}
