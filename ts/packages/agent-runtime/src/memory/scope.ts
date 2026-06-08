export interface MemoryScope {
  namespace: string;
  projectId?: string;
  host?: string;
  repo?: string;
  workdir?: string;
}

export function memoryScopeKey(scope: MemoryScope): string {
  return [
    normalizeField(scope.namespace),
    normalizeField(scope.projectId),
    normalizeField(scope.host),
    normalizePath(scope.repo),
    normalizePath(scope.workdir),
  ].join("|");
}

export function sameMemoryScope(left: MemoryScope, right: MemoryScope): boolean {
  return memoryScopeKey(left) === memoryScopeKey(right);
}

function normalizeField(value: string | undefined): string {
  const normalized = value?.trim();
  return normalized ? normalized : "-";
}

function normalizePath(value: string | undefined): string {
  const normalized = normalizeField(value);
  if (normalized === "-") return normalized;
  return normalized.replace(/\/+$/, "") || "/";
}
