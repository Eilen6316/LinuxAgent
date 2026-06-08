import { access, stat } from "node:fs/promises";
import { dirname } from "node:path";
import { PolicyEngine } from "../../../../packages/policy/src/index.js";

export interface CheckInput {
  configPath: string;
  policyPath: string;
  auditPath: string;
}

export interface CheckResult {
  ok: boolean;
  checks: CheckItem[];
}

interface CheckItem {
  name: string;
  ok: boolean;
  message: string;
}

export async function runCheck(input: CheckInput): Promise<CheckResult> {
  const checks: CheckItem[] = [];
  checks.push(await checkReadable("config", input.configPath));
  checks.push(await checkPrivateMode("config_mode", input.configPath));
  checks.push(await checkPolicy(input.policyPath));
  checks.push(await checkReadable("audit_parent", dirname(input.auditPath)));
  return { ok: checks.every((check) => check.ok), checks };
}

export async function runCheckCommand(input?: CheckInput): Promise<string> {
  if (!input) return "linuxagent-ts check";
  return formatCheckResult(await runCheck(input));
}

async function checkReadable(name: string, path: string): Promise<CheckItem> {
  try {
    await access(path);
    return { name, ok: true, message: `${path} is accessible` };
  } catch (error) {
    return { name, ok: false, message: String(error) };
  }
}

async function checkPrivateMode(name: string, path: string): Promise<CheckItem> {
  try {
    const mode = (await stat(path)).mode & 0o777;
    return (mode & 0o077) === 0
      ? { name, ok: true, message: "mode is private" }
      : { name, ok: false, message: `mode must not be group/world readable: ${mode.toString(8)}` };
  } catch (error) {
    return { name, ok: false, message: String(error) };
  }
}

async function checkPolicy(path: string): Promise<CheckItem> {
  try {
    await PolicyEngine.loadFromYaml(path);
    return { name: "policy", ok: true, message: "policy loaded" };
  } catch (error) {
    return { name: "policy", ok: false, message: String(error) };
  }
}

function formatCheckResult(result: CheckResult): string {
  const lines = result.checks.map((check) => {
    const status = check.ok ? "ok" : "fail";
    return `${status} ${check.name}: ${check.message}`;
  });
  return [`linuxagent-ts check: ${result.ok ? "ok" : "failed"}`, ...lines].join("\n");
}
