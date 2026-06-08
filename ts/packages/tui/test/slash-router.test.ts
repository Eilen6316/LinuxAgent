import { describe, expect, it } from "vitest";

import { routeSlashCommand } from "../src/slash-router.js";

describe("routeSlashCommand", () => {
  it.each([
    ["/new", "new"],
    ["/resume", "resume"],
    ["/tools", "tools"],
    ["/quit", "quit"],
  ] as const)("routes %s", (input, action) => {
    expect(routeSlashCommand(input)).toEqual({ kind: action });
  });

  it("ignores non-slash input", () => {
    expect(routeSlashCommand("check kernel")).toEqual({ kind: "not_slash" });
  });

  it("rejects unknown slash commands", () => {
    expect(routeSlashCommand("/memory")).toEqual({
      kind: "unknown",
      usage: "/new /resume /tools /quit",
    });
  });
});
