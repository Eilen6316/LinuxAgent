import { describe, expect, it } from "vitest";
import type { PolicyDecision } from "../../contracts/src/index.js";
import { SessionPermissions } from "../src/session-permissions.js";
import { type ApprovalPort, type AuditPort, LinuxAgentToolGate } from "../src/tool-gate.js";

class StubPolicy {
  constructor(private readonly decision: PolicyDecision) {}

  evaluate(): PolicyDecision {
    return this.decision;
  }
}

class RecordingAudit implements AuditPort {
  readonly events: Array<{ eventType: string; payload: Record<string, unknown> }> = [];

  async append(eventType: string, payload: Record<string, unknown>): Promise<void> {
    this.events.push({ eventType, payload });
  }
}

class StaticApproval implements ApprovalPort {
  constructor(private readonly decision: "approve_once" | "approve_thread" | "deny") {}

  async requestApproval(): Promise<"approve_once" | "approve_thread" | "deny"> {
    return this.decision;
  }
}

describe("LinuxAgentToolGate", () => {
  it("blocks policy BLOCK decisions and writes audit", async () => {
    const audit = new RecordingAudit();
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("BLOCK", true)),
      new SessionPermissions(),
      new StaticApproval("approve_once"),
      audit,
      "t1",
    );

    const result = await gate.beforeToolCall({ args: { argv: ["rm", "-rf", "/"] } });

    expect(result).toEqual({ block: true, reason: "blocked" });
    expect(audit.events[0]?.eventType).toBe("policy.block");
  });

  it("persists approve_thread only for whitelistable decisions", async () => {
    const permissions = new SessionPermissions();
    const audit = new RecordingAudit();
    const argv = ["uname", "-a"];
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("CONFIRM", false)),
      permissions,
      new StaticApproval("approve_thread"),
      audit,
      "t1",
    );

    await gate.beforeToolCall({ args: { argv } });

    expect(permissions.isAllowed({ threadId: "t1" }, argv)).toBe(true);
    expect(audit.events.at(-1)?.eventType).toBe("hitl.decision");
  });

  it("does not persist never-whitelist approvals", async () => {
    const permissions = new SessionPermissions();
    const argv = ["systemctl", "stop", "nginx"];
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("CONFIRM", true)),
      permissions,
      new StaticApproval("approve_thread"),
      new RecordingAudit(),
      "t1",
    );

    await gate.beforeToolCall({ args: { argv } });

    expect(permissions.isAllowed({ threadId: "t1" }, argv)).toBe(false);
  });
});

function decision(level: "SAFE" | "CONFIRM" | "BLOCK", neverWhitelist: boolean): PolicyDecision {
  return {
    level,
    reason: level === "BLOCK" ? "blocked" : "confirm",
    riskScore: level === "BLOCK" ? 100 : 60,
    capabilities: [],
    matchedRules: [],
    neverWhitelist,
  };
}
