import type { BulkMoveResult, DeleteFolderResult, Scope, ScopeAccess } from './scopes.types';

export interface UniqueApiScopesFacade {
  createFromPaths(
    paths: string[],
    opts?: {
      includePermissions?: boolean;
      inheritAccess?: boolean;
    },
  ): Promise<Scope[]>;
  getById(id: string): Promise<Scope | null>;
  getByExternalId(externalId: string): Promise<Scope | null>;
  getByExternalIds(externalIds: string[]): Promise<Scope[]>;
  updateExternalId(
    scopeId: string,
    externalId: string | null,
  ): Promise<{ id: string; externalId: string | null }>;
  updateParent(
    scopeId: string,
    newParentId: string,
  ): Promise<{ id: string; parentId: string | null }>;
  listChildren(parentId: string): Promise<Scope[]>;
  bulkMove(scopeIds: string[], targetScopeId: string): Promise<BulkMoveResult>;
  createAccesses(
    scopeId: string,
    accesses: ScopeAccess[],
    applyToSubScopes?: boolean,
  ): Promise<void>;
  deleteAccesses(
    scopeId: string,
    accesses: ScopeAccess[],
    applyToSubScopes?: boolean,
  ): Promise<void>;
  delete(scopeId: string, options?: { recursive?: boolean }): Promise<DeleteFolderResult>;
}
