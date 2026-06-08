export interface PermissionScope {
  threadId: string;
  resumedFromThreadId?: string;
}

export class SessionPermissions {
  private readonly allowed = new Map<string, Set<string>>();

  allow(scope: PermissionScope, argv: readonly string[]): void {
    const key = this.scopeKey(scope);
    const set = this.allowed.get(key) ?? new Set<string>();
    set.add(this.commandShape(argv));
    this.allowed.set(key, set);
  }

  isAllowed(scope: PermissionScope, argv: readonly string[]): boolean {
    return this.allowed.get(this.scopeKey(scope))?.has(this.commandShape(argv)) ?? false;
  }

  commandShape(argv: readonly string[]): string {
    return JSON.stringify(argv);
  }

  private scopeKey(scope: PermissionScope): string {
    return scope.resumedFromThreadId ?? scope.threadId;
  }
}
