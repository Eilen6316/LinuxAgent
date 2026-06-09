import { formatAuditVerifyResult, runAuditVerifyCommand } from "./commands/audit.js";
import { runChatCommand } from "./commands/chat.js";
import { type CheckInput, formatCheckResult, runCheck, runCheckCommand } from "./commands/check.js";

export interface CliPorts {
  stdout?: (text: string) => void;
  stderr?: (text: string) => void;
}

export async function runCli(argv: readonly string[], ports: CliPorts = {}): Promise<number> {
  const stdout = ports.stdout ?? console.log;
  const stderr = ports.stderr ?? console.error;
  const [command, subcommand, ...rest] = argv;

  if (command === "check") {
    const parsed = parseCheckInput([subcommand, ...rest].filter((arg) => arg !== undefined));
    if (parsed.ok === false) {
      stderr(`${parsed.error}\n\n${usage()}`);
      return 2;
    }
    if (parsed.input === undefined) {
      stdout(await runCheckCommand());
      return 0;
    }
    const result = await runCheck(parsed.input);
    stdout(formatCheckResult(result));
    return result.ok ? 0 : 1;
  }
  if (command === "chat") {
    const parsed = parseChatInput([subcommand, ...rest].filter((arg) => arg !== undefined));
    if (parsed.ok === false) {
      stderr(`${parsed.error}\n\n${usage()}`);
      return 2;
    }
    stdout(await runChatCommand(parsed.input));
    return 0;
  }
  if (command === "audit" && subcommand === "verify") {
    const path = rest[0];
    if (path === undefined) {
      stderr(`audit verify requires a path\n\n${usage()}`);
      return 2;
    }
    if (rest.length > 1) {
      stderr(`audit verify accepts exactly one path\n\n${usage()}`);
      return 2;
    }
    const result = await runAuditVerifyCommand(path);
    stdout(formatAuditVerifyResult(result));
    return result.status === "valid" ? 0 : 1;
  }

  stderr(usage());
  return 2;
}

function usage(): string {
  return [
    "Usage: linuxagent-ts <command>",
    "",
    "Commands:",
    "  check [--config <path> --policy <path> --audit <path>]",
    "  chat [--input <text>]",
    "  audit verify <path>",
  ].join("\n");
}

type ParseCheckResult = { ok: true; input?: CheckInput } | { ok: false; error: string };

function parseCheckInput(args: readonly string[]): ParseCheckResult {
  if (args.length === 0) return { ok: true };

  const values: Partial<CheckInput> = {};
  for (let index = 0; index < args.length; index += 2) {
    const flag = args[index];
    const value = args[index + 1];
    if (value === undefined) return { ok: false, error: `${flag} requires a value` };
    switch (flag) {
      case "--config":
        values.configPath = value;
        break;
      case "--policy":
        values.policyPath = value;
        break;
      case "--audit":
        values.auditPath = value;
        break;
      default:
        return { ok: false, error: `unknown check flag: ${flag}` };
    }
  }

  const missing = ["configPath", "policyPath", "auditPath"].filter(
    (key) => values[key as keyof CheckInput] === undefined,
  );
  if (missing.length > 0) return { ok: false, error: `missing check option: ${missing[0]}` };
  return { ok: true, input: values as CheckInput };
}

type ParseChatResult = { ok: true; input?: string } | { ok: false; error: string };

function parseChatInput(args: readonly string[]): ParseChatResult {
  if (args.length === 0) return { ok: true };
  if (args[0] !== "--input") return { ok: false, error: `unknown chat flag: ${args[0]}` };
  if (args[1] === undefined) return { ok: false, error: "--input requires a value" };
  if (args.length > 2) return { ok: false, error: "chat accepts only one --input value" };
  return { ok: true, input: args[1] };
}

if (isCliEntrypoint(process.argv[1])) {
  process.exitCode = await runCli(process.argv.slice(2));
}

function isCliEntrypoint(entrypoint: string | undefined): boolean {
  return entrypoint?.endsWith("/cli.js") ?? false;
}
