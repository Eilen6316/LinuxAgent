import type { MemoryScope } from "./scope.js";

export interface PendingMemoryCandidateInput {
  text: string;
  source: string;
  scope: MemoryScope;
}

export interface PendingMemoryCandidateRef {
  id: string;
  sourcePath: string;
}

export interface MemoryWriteStore {
  addPendingCandidate(
    input: PendingMemoryCandidateInput,
  ): Promise<PendingMemoryCandidateRef | null>;
}

export type PendingMemoryCandidateResult =
  | { pending: true; id: string; sourcePath: string }
  | { pending: false };

export async function createPendingMemoryCandidate(
  store: MemoryWriteStore,
  input: PendingMemoryCandidateInput,
): Promise<PendingMemoryCandidateResult> {
  const text = input.text.trim();
  if (!text) return { pending: false };
  const candidate = await store.addPendingCandidate({ ...input, text });
  if (candidate === null) return { pending: false };
  return { pending: true, id: candidate.id, sourcePath: candidate.sourcePath };
}
