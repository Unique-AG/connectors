import { UniqueAccessType, UniqueEntityType } from '../types';

export interface Scope {
  id: string;
  name: string;
  parentId: string | null;
  scopeAccess?: ScopeAccess[];
}

export interface ScopeAccess {
  type: UniqueAccessType;
  entityId: string;
  entityType: UniqueEntityType;
}
