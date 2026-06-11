import { redactOutput } from "@linuxagent/executor";
import type { WorkspaceToolConfig } from "./workspace.js";

export interface WorkspaceToolSuccessDetails {
  ok: true;
  redacted: boolean;
  truncated: boolean;
}

export interface WorkspaceToolErrorDetails {
  ok: false;
  error: string;
}

export type WorkspaceToolDetails<T extends Record<string, unknown>> =
  | (T & WorkspaceToolSuccessDetails)
  | WorkspaceToolErrorDetails;

export async function workspaceToolResult<T extends Record<string, unknown>>(
  config: WorkspaceToolConfig,
  run: () => Promise<{ text: string; details: T }>,
): Promise<{
  content: Array<{ type: "text"; text: string }>;
  details: WorkspaceToolDetails<T>;
  terminate?: boolean;
}> {
  try {
    const result = await run();
    const modelOutput = redactOutput(result.text, config.maxPreviewChars);
    return {
      content: [{ type: "text", text: modelOutput.text }],
      details: {
        ...result.details,
        ok: true,
        redacted: modelOutput.redacted,
        truncated: modelOutput.truncated,
      },
    };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return {
      content: [{ type: "text", text: `ok=false\nerror=${message}` }],
      details: { ok: false, error: message },
      terminate: true,
    };
  }
}
