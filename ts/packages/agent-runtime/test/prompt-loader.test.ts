import { describe, expect, it } from "vitest";

import { PromptLoader } from "../src/prompt-loader.js";

describe("PromptLoader", () => {
  it("loads prompts from the configured root", async () => {
    const loader = new PromptLoader("../prompts");

    await expect(loader.load("planner.md")).resolves.toContain("LinuxAgent");
  });

  it("rejects path traversal before reading from disk", async () => {
    const loader = new PromptLoader("../prompts");

    await expect(loader.load("../secret.md")).rejects.toThrow("invalid prompt name");
  });

  it("rejects absolute prompt paths", async () => {
    const loader = new PromptLoader("../prompts");

    await expect(loader.load("/secret.md")).rejects.toThrow("invalid prompt name");
  });
});
