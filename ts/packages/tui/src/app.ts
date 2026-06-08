export interface LinuxAgentTuiApp {
  readonly name: "linuxagent-ts";
}

export function createLinuxAgentTuiApp(): LinuxAgentTuiApp {
  return { name: "linuxagent-ts" };
}
