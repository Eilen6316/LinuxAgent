import { describe, expect, it } from "vitest";

import { validateUnifiedDiff } from "../../src/file-patch/diff-validator.js";

describe("validateUnifiedDiff", () => {
  it("accepts create and update unified diffs", () => {
    expect(
      validateUnifiedDiff("--- /dev/null\n+++ /tmp/app.conf\n@@ -0,0 +1 @@\n+enabled=true\n"),
    ).toEqual({
      files: [{ oldPath: "/dev/null", newPath: "/tmp/app.conf", hunks: 1 }],
    });

    expect(
      validateUnifiedDiff(
        "--- /tmp/app.conf\n+++ /tmp/app.conf\n@@ -1 +1 @@\n-enabled=false\n+enabled=true\n",
      ),
    ).toEqual({
      files: [{ oldPath: "/tmp/app.conf", newPath: "/tmp/app.conf", hunks: 1 }],
    });
  });

  it("rejects missing file patch headers", () => {
    expect(() => validateUnifiedDiff("@@ -1 +1 @@\n-old\n+new\n")).toThrow(
      "unified diff contains no file patches",
    );
  });

  it("rejects missing new file headers", () => {
    expect(() => validateUnifiedDiff("--- /tmp/app.conf\n@@ -1 +1 @@\n-old\n+new\n")).toThrow(
      "unified diff missing +++ header",
    );
  });

  it("rejects file patches without hunks", () => {
    expect(() => validateUnifiedDiff("--- /tmp/app.conf\n+++ /tmp/app.conf\n")).toThrow(
      "unified diff file patch contains no hunks",
    );
  });

  it("rejects invalid hunk headers and line markers", () => {
    expect(() => validateUnifiedDiff("--- a\n+++ b\n@@ invalid @@\n-old\n+new\n")).toThrow(
      "invalid hunk header",
    );
    expect(() => validateUnifiedDiff("--- a\n+++ b\n@@ -1 +1 @@\nold\n+new\n")).toThrow(
      "invalid hunk marker",
    );
  });
});
