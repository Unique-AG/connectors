import { randomUUID } from 'node:crypto';
import type { UniqueAccessType, UniqueEntityType } from '../../../src/unique-api/types';
import type { FileAccessKey } from '../../../src/unique-api/unique-files/unique-files.types';

export interface UniqueMockUser {
  id: string;
  email?: string;
  active?: boolean;
}

export interface UniqueMockGroupMember {
  entityId: string;
}

export interface UniqueMockGroup {
  id: string;
  name: string;
  externalId: string | null;
  members: UniqueMockGroupMember[];
}

export interface UniqueMockScopeAccess {
  entityId: string;
  entityType: UniqueEntityType;
  type: UniqueAccessType;
}

export interface UniqueMockScope {
  id: string;
  name: string;
  parentId: string | null;
  externalId: string | null;
  scopeAccess?: UniqueMockScopeAccess[];
}

export interface UniqueMockContent {
  id: string;
  key: string;
  title: string;
  mimeType: string;
  byteSize: number | null;
  ownerType: 'Scope';
  ownerId: string;
  fileAccess: FileAccessKey[];
}

export interface UniqueMockStore {
  usersById: Map<string, UniqueMockUser>;
  groupsById: Map<string, UniqueMockGroup>;
  scopesById: Map<string, UniqueMockScope>;
  contentsById: Map<string, UniqueMockContent>;
  contentsByKey: Map<string, UniqueMockContent>;
}

export interface UniqueMockSeedState {
  users?: UniqueMockUser[];
  groups?: UniqueMockGroup[];
  scopes?: UniqueMockScope[];
  contents?: Array<{
    id?: string;
    key: string;
    title: string;
    mimeType: string;
    ownerId: string;
    byteSize?: number | null;
    fileAccess?: FileAccessKey[];
  }>;
}

export function createUniqueMockStore(): UniqueMockStore {
  return {
    usersById: new Map(),
    groupsById: new Map(),
    scopesById: new Map(),
    contentsById: new Map(),
    contentsByKey: new Map(),
  };
}

export function resetUniqueMockStore(store: UniqueMockStore): void {
  store.usersById.clear();
  store.groupsById.clear();
  store.scopesById.clear();
  store.contentsById.clear();
  store.contentsByKey.clear();
}

export function seedUniqueMockStore(store: UniqueMockStore, seed: UniqueMockSeedState): void {
  if (seed.users) {
    for (const user of seed.users) {
      store.usersById.set(user.id, user);
    }
  }

  if (seed.groups) {
    for (const group of seed.groups) {
      store.groupsById.set(group.id, group);
    }
  }

  if (seed.scopes) {
    for (const scope of seed.scopes) {
      store.scopesById.set(scope.id, scope);
    }
  }

  if (seed.contents) {
    for (const contentSeed of seed.contents) {
      const id = contentSeed.id ?? randomUUID();
      const existingByKey = store.contentsByKey.get(contentSeed.key);
      const content: UniqueMockContent = {
        id,
        key: contentSeed.key,
        title: contentSeed.title,
        mimeType: contentSeed.mimeType,
        byteSize: contentSeed.byteSize ?? null,
        ownerType: 'Scope',
        ownerId: contentSeed.ownerId,
        fileAccess: contentSeed.fileAccess ?? [],
      };
      if (existingByKey && existingByKey.id !== id) {
        store.contentsById.delete(existingByKey.id);
      }
      store.contentsById.set(id, content);
      store.contentsByKey.set(content.key, content);
    }
  }
}

export function toFileAccessKey(input: {
  entityType: UniqueEntityType;
  entityId: string;
  accessType: UniqueAccessType;
}): FileAccessKey {
  const granteePrefix = input.entityType === 'USER' ? 'u' : 'g';
  const modifier = accessTypeToModifier(input.accessType);
  return `${granteePrefix}:${input.entityId}${modifier}`;
}

function accessTypeToModifier(accessType: UniqueAccessType): 'R' | 'W' | 'M' {
  switch (accessType) {
    case 'READ':
      return 'R';
    case 'WRITE':
      return 'W';
    case 'MANAGE':
      return 'M';
  }
}
