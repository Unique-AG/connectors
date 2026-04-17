import { Scope } from '../unique-api/unique-scopes/unique-scopes.types';
import { extractRootSiteId } from '../utils/scope-external-id';

// Attributes each scope to its root site by walking parentId chains upward.
// Scopes form a tree: root scope -> drives -> folders -> etc.
// Root scopes are recognized in BOTH legacy (spc:site:{id}) and new (spc:{id}/site) formats so that
// a partially-migrated site — where the root has already been flipped to new format but some
// children are still legacy — continues to group children correctly. In practice the root scope is
// migrated last, but we handle that case just in case.
export function groupScopesByRootSiteId(scopes: Scope[]): Map<string, Scope[]> {
  const scopeById = new Map<string, Scope>();
  const rootScopeIdToSiteId = new Map<string, string>();

  for (const scope of scopes) {
    scopeById.set(scope.id, scope);
    if (scope.externalId) {
      const rootSiteId = extractRootSiteId(scope.externalId);
      if (rootSiteId) {
        rootScopeIdToSiteId.set(scope.id, rootSiteId);
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
