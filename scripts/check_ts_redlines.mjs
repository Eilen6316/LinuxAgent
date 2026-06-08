import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const root = process.argv[2] ? resolve(process.argv[2]) : resolve(scriptDir, "../ts");
const violations = [];

const checks = [
  [
    "child_process exec import",
    /import\s+\{[^}]*\bexec\b[^}]*\}\s+from\s+["']node:child_process["']/,
  ],
  ["child_process exec require", /require\s*\(\s*["']node:child_process["']\s*\).*?\bexec\b/s],
  ["exec command call", /\bexec\s*\(\s*command\s*[,)]/],
  ["string policy includes", /\.includes\s*\(\s*["'`][^"'`]*(rm|mkfs|dd|sudo|systemctl)/],
  ["env secret authority", /process\.env\.(OPENAI_API_KEY|ANTHROPIC_API_KEY|DEEPSEEK_API_KEY)/],
  ["TOFU ssh host trust", /AutoAddPolicy|StrictHostKeyChecking=no|UserKnownHostsFile=\/dev\/null/],
];

function walk(dir) {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    const stat = statSync(path);
    if (stat.isDirectory()) {
      if (["node_modules", "dist", "coverage", ".git"].includes(entry)) continue;
      walk(path);
      continue;
    }
    if (!/\.(ts|tsx|js|mjs)$/.test(entry)) continue;
    const text = readFileSync(path, "utf8");
    for (const [name, pattern] of checks) {
      if (pattern.test(text)) violations.push(`${path}: ${name}`);
    }
  }
}

if (existsSync(root)) {
  walk(root);
}

if (violations.length > 0) {
  console.error(violations.join("\n"));
  process.exit(1);
}
