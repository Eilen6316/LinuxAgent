import { describe, expect, it } from "vitest";
import { SessionPermissions } from "../src/session-permissions.js";

describe("SessionPermissions", () => {
  it("allows only the same thread or resumed thread", () => {
    const permissions = new SessionPermissions();
    permissions.allow({ threadId: "t1" }, ["uname", "-a"]);

    expect(permissions.isAllowed({ threadId: "t1" }, ["uname", "-a"])).toBe(true);
    expect(permissions.isAllowed({ threadId: "t2" }, ["uname", "-a"])).toBe(false);
    expect(
      permissions.isAllowed({ threadId: "resume", resumedFromThreadId: "t1" }, ["uname", "-a"]),
    ).toBe(true);
  });
});
