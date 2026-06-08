export interface RemoteCommandGuardResult {
  level: "SAFE" | "CONFIRM" | "BLOCK";
  reason: string | null;
}

export function guardRemoteCommand(command: string): RemoteCommandGuardResult {
  if (command.includes("$(") || command.includes("`")) {
    return { level: "BLOCK", reason: "remote command substitution is blocked" };
  }
  if (/[|;&]/.test(command) || /(^|\s)(>|>>|<|2>|&>)(\s|$)/.test(command)) {
    return { level: "CONFIRM", reason: "remote shell metacharacter requires review" };
  }
  return { level: "SAFE", reason: null };
}
