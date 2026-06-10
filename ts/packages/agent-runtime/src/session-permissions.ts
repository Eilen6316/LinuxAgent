export interface PermissionScope {
  threadId: string;
  resumedFromThreadId?: string;
}

export interface SessionPermissionsSnapshot {
  scopes: Array<{
    threadId: string;
    commandShapes: string[];
  }>;
}

export class SessionPermissions {
  private readonly allowed = new Map<string, Set<string>>();

  static fromSnapshot(snapshot: SessionPermissionsSnapshot | undefined): SessionPermissions {
    const permissions = new SessionPermissions();
    if (snapshot === undefined) return permissions;
    for (const scope of snapshot.scopes) {
      permissions.allowed.set(scope.threadId, new Set(scope.commandShapes));
    }
    return permissions;
  }

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

  snapshot(): SessionPermissionsSnapshot {
    return {
      scopes: [...this.allowed.entries()]
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([threadId, commandShapes]) => ({
          threadId,
          commandShapes: [...commandShapes].sort(),
        })),
    };
  }

  private scopeKey(scope: PermissionScope): string {
    return scope.resumedFromThreadId ?? scope.threadId;
  }
}
