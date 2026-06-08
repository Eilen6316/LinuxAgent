import { describe, expect, it } from "vitest";
import type { MemoryScope } from "../../src/memory/scope.js";
import {
  createPendingMemoryCandidate,
  type MemoryWriteStore,
} from "../../src/memory/write-path.js";

class InMemoryWriteStore implements MemoryWriteStore {
  readonly pending: Array<{ text: string; source: string; scope: MemoryScope }> = [];

  constructor(private readonly enabled: boolean) {}

  async addPendingCandidate(input: {
    text: string;
    source: string;
    scope: MemoryScope;
  }): Promise<{ id: string; sourcePath: string } | null> {
    if (!this.enabled) return null;
    this.pending.push(input);
    return {
      id: `pending:${this.pending.length}`,
      sourcePath: `/mem/pending/${this.pending.length}.md`,
    };
  }
}

describe("createPendingMemoryCandidate", () => {
  it("writes generated memory to pending state only", async () => {
    const scope = { namespace: "default", repo: "/srv/app", workdir: "/srv/app" };
    const store = new InMemoryWriteStore(true);

    const result = await createPendingMemoryCandidate(store, {
      text: "Prefer staging before prod.",
      source: "chat-history",
      scope,
    });

    expect(result).toEqual({
      pending: true,
      id: "pending:1",
      sourcePath: "/mem/pending/1.md",
    });
    expect(store.pending).toEqual([
      { text: "Prefer staging before prod.", source: "chat-history", scope },
    ]);
  });

  it("no-ops when memory is disabled", async () => {
    const store = new InMemoryWriteStore(false);

    await expect(
      createPendingMemoryCandidate(store, {
        text: "Prefer staging before prod.",
        source: "chat-history",
        scope: { namespace: "default", repo: "/srv/app", workdir: "/srv/app" },
      }),
    ).resolves.toEqual({ pending: false });
    expect(store.pending).toEqual([]);
  });

  it("ignores empty generated memory", async () => {
    const store = new InMemoryWriteStore(true);

    await expect(
      createPendingMemoryCandidate(store, {
        text: "   ",
        source: "chat-history",
        scope: { namespace: "default" },
      }),
    ).resolves.toEqual({ pending: false });
    expect(store.pending).toEqual([]);
  });
});
