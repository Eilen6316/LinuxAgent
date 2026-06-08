const HUNK_HEADER = /^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@/;

export interface UnifiedDiffValidationResult {
  files: Array<{
    oldPath: string;
    newPath: string;
    hunks: number;
  }>;
}

export function validateUnifiedDiff(diff: string): UnifiedDiffValidationResult {
  const lines = diff.split(/\r?\n/);
  const files: UnifiedDiffValidationResult["files"] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (line === undefined || !line.startsWith("--- ")) {
      index += 1;
      continue;
    }
    const oldPath = cleanDiffPath(line.slice(4));
    index += 1;
    const newHeader = lines[index];
    if (newHeader === undefined || !newHeader.startsWith("+++ ")) {
      throw new Error("unified diff missing +++ header");
    }
    const newPath = cleanDiffPath(newHeader.slice(4));
    index += 1;
    let hunks = 0;
    while (index < lines.length && !lines[index]?.startsWith("--- ")) {
      const current = lines[index];
      if (current === undefined || current === "") {
        index += 1;
        continue;
      }
      if (!current.startsWith("@@ ")) {
        index += 1;
        continue;
      }
      validateHunkHeader(current);
      hunks += 1;
      index += 1;
      while (
        index < lines.length &&
        !lines[index]?.startsWith("@@ ") &&
        !lines[index]?.startsWith("--- ")
      ) {
        validateHunkLine(lines[index] ?? "");
        index += 1;
      }
    }
    if (hunks === 0) {
      throw new Error("unified diff file patch contains no hunks");
    }
    files.push({ oldPath, newPath, hunks });
  }
  if (files.length === 0) {
    throw new Error("unified diff contains no file patches");
  }
  return { files };
}

function validateHunkHeader(header: string): void {
  if (!HUNK_HEADER.test(header)) throw new Error(`invalid hunk header: ${header}`);
}

function validateHunkLine(line: string): void {
  if (line === "") return;
  const marker = line[0];
  if (marker !== " " && marker !== "+" && marker !== "-" && marker !== "\\") {
    throw new Error(`invalid hunk marker: ${marker}`);
  }
}

function cleanDiffPath(path: string): string {
  const clean = path.trim().split("\t", 1)[0] ?? "";
  if (clean.startsWith("a/") || clean.startsWith("b/")) return clean.slice(2);
  return clean;
}
