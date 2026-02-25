import type { UniqueAccessType, UniqueEntityType } from '../types';

export interface Scope {
  id: string;
  name: string;
  parentId: string | null;
  externalId: string | null;
  scopeAccess?: ScopeAccess[];
}

export interface ScopeWithPath extends Scope {
  path: string;
}

export interface ScopeAccess {
  type: UniqueAccessType;
  entityId: string;
  entityType: UniqueEntityType;
}

export interface DeleteFolderResult {
  successFolders: Array<{
    id: string;
    name: string;
    path: string;
  }>;
  failedFolders: Array<{
    id: string;
    name: string;
    failReason: string;
    path: string;
  }>;
}
