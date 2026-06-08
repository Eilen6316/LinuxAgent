import { describe, expect, it } from "vitest";

import { guardRemoteCommand } from "../src/remote-command.js";

describe("guardRemoteCommand", () => {
  it("blocks remote command substitution", () => {
    expect(guardRemoteCommand("echo $(cat /etc/shadow)")).toEqual({
      level: "BLOCK",
      reason: "remote command substitution is blocked",
    });
  });

  it("requires review for remote pipes", () => {
    expect(guardRemoteCommand("journalctl | tail")).toEqual({
      level: "CONFIRM",
      reason: "remote shell metacharacter requires review",
    });
  });

  it("allows simple remote argv-like commands", () => {
    expect(guardRemoteCommand("systemctl status nginx --no-pager")).toEqual({
      level: "SAFE",
      reason: null,
    });
  });
});
