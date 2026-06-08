import { describe, expect, it } from "vitest";
import { redactOutput } from "../src/output-redaction.js";

describe("redactOutput", () => {
  it("redacts bearer tokens before model-facing analysis", () => {
    const result = redactOutput("Authorization: Bearer secret-token-value");

    expect(result.text).not.toContain("secret-token-value");
    expect(result.redacted).toBe(true);
  });

  it("truncates bounded output after redaction", () => {
    const result = redactOutput(`token sk-${"a".repeat(32)} ${"x".repeat(20)}`, 20);

    expect(result.text).toContain("[REDACTED]");
    expect(result.text).not.toContain("sk-");
    expect(result.text).toContain("[TRUNCATED]");
    expect(result.truncated).toBe(true);
  });
});
