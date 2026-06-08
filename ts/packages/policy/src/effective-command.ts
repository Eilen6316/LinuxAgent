import { parseArgv } from "./argv.js";
import { analyzeShellStructure } from "./shell-structure.js";

export interface EffectiveCommand {
  executable: string;
  normalizedExecutable: string;
  args: string[];
  shell: ReturnType<typeof analyzeShellStructure>;
}

export function buildEffectiveCommand(argv: readonly string[]): EffectiveCommand {
  const parsed = parseArgv(argv);
  return {
    executable: parsed.executable,
    normalizedExecutable: parsed.normalizedExecutable,
    args: parsed.args,
    shell: analyzeShellStructure(parsed.argv),
  };
}
