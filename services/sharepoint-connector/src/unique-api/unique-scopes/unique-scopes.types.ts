export interface Scope {
  id: string;
  name: string;
  parentId: string | null;
  scopeAccess?: ScopeAccess[];
  path?: string;
}

export interface ScopeAccess {
  entityId: string;
  type: string;
  entityType: string;
}
