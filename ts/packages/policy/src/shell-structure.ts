import { normalizeExecutable } from "./argv.js";

const SHELLS = new Set(["sh", "bash", "dash", "zsh", "fish"]);

export interface ShellStructure {
  invokesShell: boolean;
  hasPipeline: boolean;
  hasRedirect: boolean;
  hasCommandSubstitution: boolean;
  hasSubshell: boolean;
  rawScript: string;
}

export function analyzeShellStructure(argv: readonly string[]): ShellStructure {
  const executable = argv[0] ?? "";
  const normalized = normalizeExecutable(executable);
  const invokesShell = SHELLS.has(normalized);
  const rawScript = argv.slice(1).join(" ");
  return {
    invokesShell,
    rawScript,
    hasPipeline: invokesShell && rawScript.includes("|"),
    hasRedirect: invokesShell && /(^|\s)(>|>>|<|2>|&>)(\s|$)/.test(rawScript),
    hasCommandSubstitution: invokesShell && (rawScript.includes("$(") || rawScript.includes("`")),
    hasSubshell: invokesShell && /(^|\s)\([^)]*\)(\s|$)/.test(rawScript),
  };
}
