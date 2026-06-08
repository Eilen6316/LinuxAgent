import { runAuditVerifyCommand } from "./commands/audit.js";
import { runChatCommand } from "./commands/chat.js";
import { runCheckCommand } from "./commands/check.js";

export interface CliPorts {
  stdout?: (text: string) => void;
  stderr?: (text: string) => void;
}

export async function runCli(argv: readonly string[], ports: CliPorts = {}): Promise<number> {
  const stdout = ports.stdout ?? console.log;
  const stderr = ports.stderr ?? console.error;
  const [command, subcommand] = argv;

  if (command === "check" && subcommand === undefined) {
    stdout(await runCheckCommand());
    return 0;
  }
  if (command === "chat" && subcommand === undefined) {
    stdout(await runChatCommand());
    return 0;
  }
  if (command === "audit" && subcommand === "verify" && argv.length === 2) {
    stdout(await runAuditVerifyCommand());
    return 0;
  }

  stderr(usage());
  return 2;
}

function usage(): string {
  return [
    "Usage: linuxagent-ts <command>",
    "",
    "Commands:",
    "  check",
    "  chat",
    "  audit verify",
  ].join("\n");
}

if (isCliEntrypoint(process.argv[1])) {
  process.exitCode = await runCli(process.argv.slice(2));
}

function isCliEntrypoint(entrypoint: string | undefined): boolean {
  return entrypoint?.endsWith("/cli.js") ?? false;
}
