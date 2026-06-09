import { type AuditVerifyResult, verifyAuditLog } from "@linuxagent/audit";

export async function runAuditVerifyCommand(path: string): Promise<AuditVerifyResult> {
  return verifyAuditLog(path);
}

export function formatAuditVerifyResult(result: AuditVerifyResult): string {
  switch (result.status) {
    case "valid":
      return `linuxagent-ts audit verify: valid (${result.entries.length} entries)`;
    case "missing":
      return "linuxagent-ts audit verify: missing";
    case "invalid":
      return `linuxagent-ts audit verify: invalid at line ${result.line}: ${result.reason}`;
  }
}
