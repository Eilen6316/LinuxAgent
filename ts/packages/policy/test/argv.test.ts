import { describe, expect, it } from "vitest";
import { parseArgv } from "../src/argv.js";

describe("parseArgv", () => {
  it("normalizes executable basename", () => {
    expect(parseArgv(["/usr/bin/systemctl", "status", "ssh"]).normalizedExecutable).toBe(
      "systemctl",
    );
  });

  it("rejects empty argv", () => {
    expect(() => parseArgv([])).toThrow("argv must contain at least one token");
  });
});
