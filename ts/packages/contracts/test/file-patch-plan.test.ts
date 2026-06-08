import { Value } from "typebox/value";
import { describe, expect, it } from "vitest";

import { FilePatchPlanSchema } from "../src/file-patch-plan.js";

describe("FilePatchPlanSchema", () => {
  it("accepts create plans with unified diff patches", () => {
    expect(
      Value.Check(FilePatchPlanSchema, {
        version: 1,
        requestIntent: "create",
        summary: "create config",
        patches: [
          {
            path: "/tmp/app.conf",
            diff: "--- /dev/null\n+++ /tmp/app.conf\n@@ -0,0 +1 @@\n+enabled=true\n",
          },
        ],
      }),
    ).toBe(true);
  });

  it("accepts update plans with permission changes", () => {
    expect(
      Value.Check(FilePatchPlanSchema, {
        version: 1,
        requestIntent: "update",
        summary: "update script",
        patches: [
          {
            path: "/tmp/deploy.sh",
            diff: "--- /tmp/deploy.sh\n+++ /tmp/deploy.sh\n@@ -1 +1 @@\n-echo old\n+echo new\n",
          },
        ],
        permissionChanges: [{ path: "/tmp/deploy.sh", mode: "0755" }],
      }),
    ).toBe(true);
  });

  it("rejects patches without target paths or diffs", () => {
    expect(
      Value.Check(FilePatchPlanSchema, {
        version: 1,
        requestIntent: "update",
        summary: "bad",
        patches: [{ path: "", diff: "not empty" }],
      }),
    ).toBe(false);
    expect(
      Value.Check(FilePatchPlanSchema, {
        version: 1,
        requestIntent: "update",
        summary: "bad",
        patches: [{ path: "/tmp/app.conf", diff: "" }],
      }),
    ).toBe(false);
  });

  it("rejects unsafe permission mode strings", () => {
    expect(
      Value.Check(FilePatchPlanSchema, {
        version: 1,
        requestIntent: "unknown",
        summary: "bad mode",
        patches: [{ path: "/tmp/app.conf", diff: "--- a\n+++ b\n" }],
        permissionChanges: [{ path: "/tmp/app.conf", mode: "u+s" }],
      }),
    ).toBe(false);
  });
});
