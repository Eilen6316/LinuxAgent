import { describe, expect, it } from "vitest";
import { createApprovalRequest, NonTtyApprovalPort } from "../src/approval.js";

describe("approval request", () => {
  it("normalizes approval request payloads", () => {
    expect(
      createApprovalRequest({
        argv: ["uname", "-a"],
        reason: null,
        neverWhitelist: false,
        threadId: "t1",
        matchedRules: ["LLM_FIRST_RUN"],
        capabilities: ["llm.generated"],
        riskScore: 30,
      }),
    ).toEqual({
      argv: ["uname", "-a"],
      reason: null,
      neverWhitelist: false,
      threadId: "t1",
      matchedRules: ["LLM_FIRST_RUN"],
      capabilities: ["llm.generated"],
      riskScore: 30,
    });
  });

  it("normalizes remote approval metadata without key material paths", () => {
    expect(
      createApprovalRequest({
        argv: ["ssh", "operator@192.0.2.10", "uptime"],
        reason: "remote command requires review",
        neverWhitelist: true,
        threadId: "t1",
        remote: {
          type: "ssh",
          host: "192.0.2.10",
          profileName: "prod-web",
          username: "operator",
          port: 22,
          knownHostsPath: "/home/operator/.ssh/known_hosts",
          allowedWorkdirs: ["/var/log"],
          sudoPolicy: "none",
          keyPath: "/home/operator/.ssh/id_ed25519",
        },
      }),
    ).toMatchObject({
      remote: {
        type: "ssh",
        host: "192.0.2.10",
        profileName: "prod-web",
        username: "operator",
        port: 22,
        knownHostsPath: "/home/operator/.ssh/known_hosts",
        allowedWorkdirs: ["/var/log"],
        sudoPolicy: "none",
      },
    });
  });

  it("rejects missing argv in approval request payloads", () => {
    expect(() => createApprovalRequest({ threadId: "t1" })).toThrow(
      "approval request requires argv",
    );
  });

  it("denies by default when no TTY approval port is available", async () => {
    await expect(
      new NonTtyApprovalPort().requestApproval(
        createApprovalRequest({
          argv: ["uname", "-a"],
          threadId: "t1",
          neverWhitelist: false,
        }),
      ),
    ).resolves.toBe("deny");
  });
});
