import { readdir, readFile, realpath, stat } from "node:fs/promises";
import { join, relative, resolve, sep } from "node:path";

export interface WorkspaceToolConfig {
  allowedRoots: string[];
  maxFileBytes?: number;
  maxMatches?: number;
  maxEntries?: number;
  maxPreviewChars?: number;
}

export async function resolveWorkspacePath(
  path: string,
  config: WorkspaceToolConfig,
): Promise<string> {
  if (path.includes("\0")) throw new Error("path contains NUL byte");
  const roots = await Promise.all(config.allowedRoots.map((root) => realpath(root)));
  const target = await realpath(resolve(path));
  if (!roots.some((root) => target === root || target.startsWith(`${root}${sep}`))) {
    throw new Error(`path outside allowed roots: ${path}`);
  }
  return target;
}

export async function readWorkspaceFile(
  path: string,
  config: WorkspaceToolConfig,
  offset = 0,
  limit = 200,
): Promise<string> {
  const target = await resolveWorkspacePath(path, config);
  const metadata = await stat(target);
  if (!metadata.isFile()) throw new Error(`path is not a file: ${path}`);
  if (metadata.size > (config.maxFileBytes ?? 1024 * 1024)) {
    throw new Error(`file exceeds max bytes: ${path}`);
  }
  const lines = (await readFile(target, "utf8")).split(/\r?\n/);
  return lines.slice(Math.max(0, offset), Math.max(0, offset) + Math.max(1, limit)).join("\n");
}

export async function listWorkspaceDir(
  path: string,
  config: WorkspaceToolConfig,
  limit = 200,
): Promise<string[]> {
  const target = await resolveWorkspacePath(path, config);
  const metadata = await stat(target);
  if (!metadata.isDirectory()) throw new Error(`path is not a directory: ${path}`);
  const entries = await readdir(target, { withFileTypes: true });
  return entries
    .slice()
    .sort((left, right) => left.name.localeCompare(right.name))
    .slice(0, Math.max(1, Math.min(limit, config.maxEntries ?? 200)))
    .map((entry) => `${entry.name}${entry.isDirectory() ? "/" : ""}`);
}

export async function searchWorkspaceFiles(
  root: string,
  pattern: string,
  config: WorkspaceToolConfig,
  maxMatches = 50,
): Promise<string[]> {
  if (pattern.length === 0) throw new Error("search pattern is required");
  const base = await resolveWorkspacePath(root, config);
  const matches: string[] = [];
  await searchDir(
    base,
    base,
    pattern,
    config,
    matches,
    Math.min(maxMatches, config.maxMatches ?? 50),
  );
  return matches;
}

async function searchDir(
  base: string,
  current: string,
  pattern: string,
  config: WorkspaceToolConfig,
  matches: string[],
  maxMatches: number,
): Promise<void> {
  if (matches.length >= maxMatches) return;
  const entries = await readdir(current, { withFileTypes: true });
  for (const entry of entries.sort((left, right) => left.name.localeCompare(right.name))) {
    if (matches.length >= maxMatches) return;
    if (entry.isSymbolicLink()) continue;
    const path = join(current, entry.name);
    if (entry.isDirectory()) {
      await searchDir(base, path, pattern, config, matches, maxMatches);
      continue;
    }
    if (!entry.isFile()) continue;
    const metadata = await stat(path);
    if (metadata.size > (config.maxFileBytes ?? 1024 * 1024)) continue;
    const lines = (await readFile(path, "utf8")).split(/\r?\n/);
    for (const [index, line] of lines.entries()) {
      if (line.includes(pattern)) {
        matches.push(`${relative(base, path)}:${index + 1}:${line}`);
        if (matches.length >= maxMatches) return;
      }
    }
  }
}
