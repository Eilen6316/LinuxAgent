import type { SandboxSpec } from "@linuxagent/sandbox";
import type { CommandExecutorPort } from "../execute-command-tool.js";
import type { PathPolicy } from "../file-patch/index.js";
import type { PatchApprovalPort, PatchAuditPort } from "../file-patch/transaction.js";
import type { LinuxAgentToolGate } from "../tool-gate.js";
import {
  createApplyFilePatchTool,
  createExecuteCommandReactTool,
  createListDirTool,
  createReadFileTool,
  createRunSshCommandTool,
  createSearchFilesTool,
  type FilePatchToolPorts,
  type ReactAgentTool,
  type SshExecutorPort,
  type WorkspaceToolConfig,
} from "./tools/index.js";

export interface ReactToolRegistryInput {
  gate: Pick<LinuxAgentToolGate, "beforeToolCall">;
  executor: CommandExecutorPort;
  sandbox: SandboxSpec;
  signal?: AbortSignal;
  workspace?: WorkspaceToolConfig;
  filePatch?: {
    pathPolicy: PathPolicy;
    approval: PatchApprovalPort;
    audit: PatchAuditPort;
  };
  ssh?: SshExecutorPort;
}

export function buildReactToolRegistry(input: ReactToolRegistryInput): ReactAgentTool[] {
  const workspace = input.workspace ?? { allowedRoots: [process.cwd()] };
  const filePatch: FilePatchToolPorts | undefined = input.filePatch;
  return [
    createReadFileTool(workspace),
    createListDirTool(workspace),
    createSearchFilesTool(workspace),
    createExecuteCommandReactTool({
      gate: input.gate,
      executor: input.executor,
      sandbox: input.sandbox,
      ...(input.signal ? { signal: input.signal } : {}),
    }),
    createApplyFilePatchTool(filePatch),
    createRunSshCommandTool(input.ssh),
  ];
}
