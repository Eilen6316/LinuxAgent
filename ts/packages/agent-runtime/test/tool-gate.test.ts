import { describe, expect, it } from "vitest";
import type { PolicyDecision } from "../../contracts/src/index.js";
import type { ApprovalPort } from "../src/approval.js";
import { SessionPermissions } from "../src/session-permissions.js";
import { type AuditPort, LinuxAgentToolGate } from "../src/tool-gate.js";

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
  callCount = 0;
  readonly requests: Parameters<ApprovalPort["requestApproval"]>[0][] = [];

  constructor(private readonly decision: "approve_once" | "approve_thread" | "deny") {}

  async requestApproval(
    request: Parameters<ApprovalPort["requestApproval"]>[0],
  ): Promise<"approve_once" | "approve_thread" | "deny"> {
    this.callCount += 1;
    this.requests.push(request);
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

  it("allows already-approved same-thread commands without another approval", async () => {
    const permissions = new SessionPermissions();
    const audit = new RecordingAudit();
    const approvals = new StaticApproval("deny");
    const argv = ["uname", "-a"];
    permissions.allow({ threadId: "t1" }, argv);
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("CONFIRM", false)),
      permissions,
      approvals,
      audit,
      "t1",
    );

    const result = await gate.beforeToolCall({ args: { argv } });

    expect(result).toBeUndefined();
    expect(approvals.callCount).toBe(0);
    expect(audit.events.at(-1)?.eventType).toBe("policy.allow");
  });

  it("includes sandbox metadata in audit payloads", async () => {
    const audit = new RecordingAudit();
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("SAFE", false)),
      new SessionPermissions(),
      new StaticApproval("approve_once"),
      audit,
      "t1",
    );

    await gate.beforeToolCall({
      args: {
        argv: ["uname", "-a"],
        sandbox: { profile: "system_inspect", timeoutMs: 5000, ignored: "value" },
      },
    });

    expect(audit.events[0]).toMatchObject({
      eventType: "policy.allow",
      payload: {
        sandbox: { profile: "system_inspect", timeoutMs: 5000 },
      },
    });
  });

  it("includes remote profile metadata in approval and audit payloads", async () => {
    const audit = new RecordingAudit();
    const approvals = new StaticApproval("approve_once");
    const remote = {
      type: "ssh",
      host: "192.0.2.10",
      profileName: "prod-web",
      username: "operator",
      port: 22,
      knownHostsPath: "/home/operator/.ssh/known_hosts",
      allowedWorkdirs: ["/var/log"],
      sudoPolicy: "none",
      keyPath: "/home/operator/.ssh/id_ed25519",
    };
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("CONFIRM", true)),
      new SessionPermissions(),
      approvals,
      audit,
      "t1",
    );

    await gate.beforeToolCall({ args: { argv: ["ssh", "operator@192.0.2.10", "uptime"], remote } });

    expect(approvals.requests[0]?.remote).toEqual({
      type: "ssh",
      host: "192.0.2.10",
      profileName: "prod-web",
      username: "operator",
      port: 22,
      knownHostsPath: "/home/operator/.ssh/known_hosts",
      allowedWorkdirs: ["/var/log"],
      sudoPolicy: "none",
    });
    expect(audit.events.at(-1)).toMatchObject({
      eventType: "hitl.decision",
      payload: {
        remote: approvals.requests[0]?.remote,
      },
    });
  });

  it("blocks remote commands before approval while preserving audit metadata", async () => {
    const audit = new RecordingAudit();
    const approvals = new StaticApproval("approve_once");
    const remote = {
      type: "ssh",
      host: "192.0.2.10",
      profileName: "prod-web",
      username: "operator",
      port: 22,
    };
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("BLOCK", true)),
      new SessionPermissions(),
      approvals,
      audit,
      "t1",
    );

    const result = await gate.beforeToolCall({
      args: { argv: ["ssh", "operator@192.0.2.10", "echo $(cat /etc/shadow)"], remote },
    });

    expect(result?.block).toBe(true);
    expect(result?.reason).toContain("remote command substitution is blocked");
    expect(approvals.callCount).toBe(0);
    expect(audit.events[0]).toMatchObject({
      eventType: "policy.block",
      payload: {
        remote,
      },
    });
  });

  it("blocks remote command substitution at the gate before SSH transport", async () => {
    const audit = new RecordingAudit();
    const approvals = new StaticApproval("approve_once");
    const remote = {
      type: "ssh",
      host: "192.0.2.10",
      profileName: "prod-web",
      username: "operator",
      port: 22,
    };
    const gate = new LinuxAgentToolGate(
      new StubPolicy(decision("SAFE", false)),
      new SessionPermissions(),
      approvals,
      audit,
      "t1",
    );

    const result = await gate.beforeToolCall({
      args: {
        argv: ["ssh", "operator@192.0.2.10", "echo $(cat /etc/shadow)"],
        remote,
      },
    });

    expect(result?.block).toBe(true);
    expect(result?.reason).toContain("remote command substitution is blocked");
    expect(approvals.callCount).toBe(0);
    expect(audit.events[0]).toMatchObject({
      eventType: "policy.block",
      payload: {
        remote,
      },
    });
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
