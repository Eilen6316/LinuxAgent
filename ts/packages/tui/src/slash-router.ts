export type SlashRoute =
  | { kind: "new" }
  | { kind: "resume" }
  | { kind: "tools" }
  | { kind: "quit" }
  | { kind: "not_slash" }
  | { kind: "unknown"; usage: string };

const USAGE = "/new /resume /tools /quit";

export function routeSlashCommand(input: string): SlashRoute {
  const command = input.trim().split(/\s+/, 1)[0] ?? "";
  if (!command.startsWith("/")) return { kind: "not_slash" };
  switch (command) {
    case "/new":
      return { kind: "new" };
    case "/resume":
      return { kind: "resume" };
    case "/tools":
      return { kind: "tools" };
    case "/quit":
      return { kind: "quit" };
    default:
      return { kind: "unknown", usage: USAGE };
  }
}
