import { redactOutput } from "@linuxagent/executor";

export interface LinuxAgentToolCallAnalysisContext {
  result: {
    details?: unknown;
  };
  isError: boolean;
}

export interface LinuxAgentToolCallAnalysisResult {
  details: Record<string, unknown>;
  isError: boolean;
}

interface ToolExecutionDetails {
  stdout?: string;
  stderr?: string;
  [key: string]: unknown;
}

export async function afterLinuxAgentToolCall(
  context: LinuxAgentToolCallAnalysisContext,
): Promise<LinuxAgentToolCallAnalysisResult> {
  const details = normalizeDetails(context.result.details);
  const stdout = redactOutput(details.stdout ?? "");
  const stderr = redactOutput(details.stderr ?? "");

  return {
    details: {
      ...details,
      stdout: stdout.text,
      stderr: stderr.text,
      outputRedaction: {
        stdout: stdout.redacted,
        stderr: stderr.redacted,
      },
    },
    isError: context.isError,
  };
}

function normalizeDetails(details: unknown): ToolExecutionDetails {
  if (!details || typeof details !== "object" || Array.isArray(details)) {
    return {};
  }
  return { ...(details as Record<string, unknown>) };
}
