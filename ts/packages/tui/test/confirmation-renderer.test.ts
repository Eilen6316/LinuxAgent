import { describe, expect, it } from "vitest";

import { renderConfirmation } from "../src/confirmation-renderer.js";

describe("renderConfirmation", () => {
  it("renders command, policy, sandbox, and whitelist status", () => {
    const text = renderConfirmation({
      argv: ["uname", "-a"],
      policy: {
        level: "CONFIRM",
        reason: "LLM-generated command; first run requires approval",
        riskScore: 30,
        capabilities: ["llm.generated"],
        matchedRules: ["LLM_FIRST_RUN"],
        neverWhitelist: false,
      },
      sandbox: {
        profile: "noop",
        runner: "noop",
        enforced: false,
      },
    });

    expect(text).toContain("argv: uname -a");
    expect(text).toContain("policy: CONFIRM");
    expect(text).toContain("reason: LLM-generated command; first run requires approval");
    expect(text).toContain("capabilities: llm.generated");
    expect(text).toContain("matched_rules: LLM_FIRST_RUN");
    expect(text).toContain("sandbox: profile=noop runner=noop enforced=false");
    expect(text).toContain("never_whitelist: false");
  });

  it("renders remote profile metadata without key material paths", () => {
    const remoteWithKeyPath = {
      type: "ssh" as const,
      host: "192.0.2.10",
      profileName: "prod-web",
      username: "operator",
      port: 22,
      knownHostsPath: "/home/operator/.ssh/known_hosts",
      allowedWorkdirs: ["/var/log"],
      sudoPolicy: "none",
      keyPath: "/home/operator/.ssh/id_ed25519",
    };

    const text = renderConfirmation({
      argv: ["ssh", "operator@192.0.2.10", "uptime"],
      policy: {
        level: "CONFIRM",
        reason: "remote command requires review",
        riskScore: 60,
        capabilities: ["ssh.remote_execute"],
        matchedRules: ["REMOTE_CONFIRM"],
        neverWhitelist: true,
      },
      sandbox: {
        profile: "noop",
        runner: "noop",
        enforced: false,
      },
      remote: remoteWithKeyPath,
    });

    expect(text).toContain(
      "remote: type=ssh host=192.0.2.10 profile=prod-web user=operator port=22",
    );
    expect(text).toContain("known_hosts=/home/operator/.ssh/known_hosts");
    expect(text).toContain("workdirs=/var/log sudo=none");
    expect(text).not.toContain("id_ed25519");
  });
});
