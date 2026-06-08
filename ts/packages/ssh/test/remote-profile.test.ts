import { describe, expect, it } from "vitest";

import { validateRemoteProfile } from "../src/remote-profile.js";

describe("validateRemoteProfile", () => {
  it("validates a documentation host profile without contacting it", () => {
    expect(
      validateRemoteProfile({
        name: "doc",
        host: "192.0.2.10",
        port: 22,
        username: "operator",
        keyPath: "/home/operator/.ssh/id_ed25519",
        knownHostsPath: "/home/operator/.ssh/known_hosts",
        allowedWorkdirs: ["/var/log"],
        sudoPolicy: "none",
      }).host,
    ).toBe("192.0.2.10");
  });

  it("rejects relative key paths", () => {
    expect(() =>
      validateRemoteProfile({
        name: "bad",
        host: "192.0.2.10",
        port: 22,
        username: "operator",
        keyPath: ".ssh/id_ed25519",
        knownHostsPath: "/home/operator/.ssh/known_hosts",
        allowedWorkdirs: ["/var/log"],
        sudoPolicy: "none",
      }),
    ).toThrow("remote key path must be absolute");
  });

  it("rejects invalid ports", () => {
    expect(() =>
      validateRemoteProfile({
        name: "bad",
        host: "192.0.2.10",
        port: 70000,
        username: "operator",
        keyPath: "/home/operator/.ssh/id_ed25519",
        knownHostsPath: "/home/operator/.ssh/known_hosts",
        allowedWorkdirs: ["/var/log"],
        sudoPolicy: "none",
      }),
    ).toThrow("remote profile port must be 1-65535");
  });
});
