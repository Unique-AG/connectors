import { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { parseLegacyExternalId } from '../utils/scope-external-id';

// Attributes each scope to its root site by walking parentId chains upward.
// Scopes form a tree: root scope (spc:site:{id}) -> drives -> folders -> etc.
// We need to know which root site each scope belongs to so the migration can
// process one site at a time.
export function groupScopesByRootSiteId(scopes: Scope[]): Map<string, Scope[]> {
  const scopeById = new Map<string, Scope>();
  const rootScopeIdToSiteId = new Map<string, string>();

  for (const scope of scopes) {
    scopeById.set(scope.id, scope);
    if (scope.externalId) {
      const parsed = parseLegacyExternalId(scope.externalId);
      if (parsed?.type === 'root') {
        rootScopeIdToSiteId.set(scope.id, parsed.siteId);
      }
    }
  }

  // Memoize resolved root site IDs so deeply nested chains only walk once —
  // each intermediate scope's result is cached for subsequent lookups.
  const resolvedRootSiteId = new Map<string, string | null>();

  const findRootSiteId = (scope: Scope): string | null => {
    const cached = resolvedRootSiteId.get(scope.id);
    if (cached !== undefined) {
      return cached;
    }

    let current: Scope | undefined = scope;
    const chain: string[] = [];

    while (current) {
      if (resolvedRootSiteId.has(current.id)) {
        const result = resolvedRootSiteId.get(current.id) ?? null;
        for (const id of chain) {
          resolvedRootSiteId.set(id, result);
        }
        return result;
      }

      const siteId = rootScopeIdToSiteId.get(current.id);
      if (siteId) {
        chain.push(current.id);
        for (const id of chain) {
          resolvedRootSiteId.set(id, siteId);
        }
        return siteId;
      }

      chain.push(current.id);
      current = current.parentId ? scopeById.get(current.parentId) : undefined;
    }

    // No root scope found — these are orphans (e.g., parent not in the fetched set).
    for (const id of chain) {
      resolvedRootSiteId.set(id, null);
    }
    return null;
  };

  const groups = new Map<string, Scope[]>();
  for (const scope of scopes) {
    const rootSiteId = findRootSiteId(scope);
    if (rootSiteId) {
      let group = groups.get(rootSiteId);
      if (!group) {
        group = [];
        groups.set(rootSiteId, group);
      }
      group.push(scope);
    }
  }

  return groups;
}
