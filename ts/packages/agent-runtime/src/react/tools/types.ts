export interface LinuxAgentToolMetadata {
  category: "read" | "execute" | "write" | "ssh";
  requiresGate: boolean;
  sandboxProfile: "read_only" | "workspace_write" | "system_inspect" | "noop";
}

export interface ReactAgentTool<TParams = unknown, TDetails = unknown> {
  name: string;
  label: string;
  description: string;
  parameters: TParams;
  executionMode?: "sequential" | "parallel";
  linuxAgent: LinuxAgentToolMetadata;
  execute(
    toolCallId: string,
    params: unknown,
    signal?: AbortSignal,
  ): Promise<{
    content: Array<{ type: "text"; text: string }>;
    details: TDetails;
    terminate?: boolean;
  }>;
}
