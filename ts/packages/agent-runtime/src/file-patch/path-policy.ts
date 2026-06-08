import { realpath } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";

export interface PathPolicy {
  allowedRoots: string[];
}

export async function assertPathAllowed(path: string, policy: PathPolicy): Promise<string> {
  if (path.includes("\0")) throw new Error("path contains NUL byte");
  const resolved = resolve(path);
  const roots = await Promise.all(policy.allowedRoots.map((root) => realpath(root)));
  const parent = await realpath(dirname(resolved));
  if (!roots.some((root) => parent === root || parent.startsWith(`${root}${sep}`))) {
    throw new Error(`path outside allowed roots: ${path}`);
  }
  return resolved;
}

export function assertModeSafe(mode: string): void {
  const parsed = Number.parseInt(mode, 8);
  if ((parsed & 0o6000) !== 0) throw new Error("setuid/setgid permission changes are blocked");
}
