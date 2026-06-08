export interface ParsedArgv {
  argv: string[];
  executable: string;
  normalizedExecutable: string;
  args: string[];
}

export function normalizeExecutable(value: string): string {
  return value.split("/").at(-1)?.toLowerCase() ?? value.toLowerCase();
}

export function parseArgv(argv: readonly string[]): ParsedArgv {
  if (argv.length === 0) throw new Error("argv must contain at least one token");
  const [executable, ...args] = argv;
  if (!executable || executable.trim() === "") throw new Error("argv[0] must be non-empty");
  return {
    argv: [...argv],
    executable,
    normalizedExecutable: normalizeExecutable(executable),
    args,
  };
}
