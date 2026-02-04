import { randomUUID } from 'node:crypto';
import type { UniqueAccessType, UniqueEntityType } from '../../../src/unique-api/types';
import type { IngestionApiResponse } from '../../../src/unique-api/unique-file-ingestion/unique-file-ingestion.types';
import type { FileAccessKey } from '../../../src/unique-api/unique-files/unique-files.types';
import { toFileAccessKey, type UniqueMockStore } from './unique-mock.store';

export type UniqueClientTarget = 'ingestion' | 'scopeManagement';

export type UniqueOperationHandler = (input: {
  operationName: string;
  variables: unknown;
  store: UniqueMockStore;
}) => unknown;

export type UniqueOperationHandlers = Record<string, UniqueOperationHandler>;

export function createDefaultUniqueOperationHandlers(): UniqueOperationHandlers {
  return {
    // Ingestion service
    ContentUpsert: ({ variables, store }) => contentUpsert({ variables, store }),
    PaginatedContent: ({ variables, store }) => paginatedContent({ variables, store }),
    PaginatedContentCount: ({ variables, store }) => paginatedContentCount({ variables, store }),
    CreateFileAccessesForContents: ({ variables, store }) =>
      changeFileAccesses({ variables, store, mode: 'add' }),
    RemoveFileAccessesForContents: ({ variables, store }) =>
      changeFileAccesses({ variables, store, mode: 'remove' }),
    ContentUpdate: ({ variables, store }) => contentUpdate({ variables, store }),
    ContentDelete: ({ variables, store }) => contentDelete({ variables, store }),
    ContentDeleteByContentIds: ({ variables, store }) =>
      contentDeleteByContentIds({ variables, store }),

    // Scope management service
    PaginatedScope: ({ variables, store }) => paginatedScope({ variables, store }),
    UpdateScope: ({ variables, store }) => updateScope({ variables, store }),
    CreateScopeAccesses: ({ variables, store }) =>
      createOrDeleteScopeAccesses({ variables, store, mode: 'add' }),
    DeleteScopeAccesses: ({ variables, store }) =>
      createOrDeleteScopeAccesses({ variables, store, mode: 'remove' }),

    // Operation name in GET_CURRENT_USER_QUERY is `User`
    User: ({ store }) => getCurrentUser({ store }),
    // Backward-compatible alias if any tests used this previously.
    GetCurrentUser: ({ store }) => getCurrentUser({ store }),
    ListUsers: ({ store }) => listUsers({ store }),
    ListGroups: ({ variables, store }) => listGroups({ variables, store }),
    CreateGroup: ({ variables, store }) => createGroup({ variables, store }),
    UpdateGroup: ({ variables, store }) => updateGroup({ variables, store }),
    DeleteGroup: ({ variables, store }) => deleteGroup({ variables, store }),
    AddGroupMembers: ({ variables, store }) => addGroupMembers({ variables, store }),
    RemoveGroupMember: ({ variables, store }) => removeGroupMember({ variables, store }),
  };
}

function contentUpsert(input: { variables: unknown; store: UniqueMockStore }): {
  contentUpsert: IngestionApiResponse;
} {
  const vars = expectObject(input.variables);
  const upsertInput = expectObject(vars.input);
  const key = expectString(upsertInput.key);
  const title = expectString(upsertInput.title);
  const mimeType = expectString(upsertInput.mimeType);
  const ownerId = expectString(vars.scopeId);
  const byteSize = expectNumber(upsertInput.byteSize);

  const existing = input.store.contentsByKey.get(key);
  const id = existing?.id ?? randomUUID();

  const fileAccess = parseFileAccess(upsertInput.fileAccess);

  const content = {
    id,
    key,
    title,
    byteSize,
    mimeType,
    ownerType: 'Scope' as const,
    ownerId,
    fileAccess,
  };

  input.store.contentsById.set(id, content);
  input.store.contentsByKey.set(key, content);

  return {
    contentUpsert: {
      id,
      key,
      title,
      byteSize,
      mimeType,
      ownerType: 'Scope',
      ownerId,
      writeUrl: 'https://upload.test.example.com/upload?key=test-key',
      readUrl: 'https://read.test.example.com/file/test-key',
      createdAt: '2025-01-01T00:00:00Z',
      internallyStoredAt: null,
      source: {
        kind: 'MICROSOFT_365_SHAREPOINT',
        name: 'Sharepoint',
      },
    },
  };
}

function parseFileAccess(value: unknown): FileAccessKey[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value)) {
    throw new Error('Unique mock ContentUpsert: input.fileAccess must be an array when provided');
  }

  const out: FileAccessKey[] = [];
  for (const entry of value) {
    if (typeof entry !== 'string') {
      throw new Error('Unique mock ContentUpsert: input.fileAccess entries must be strings');
    }
    // FileAccessKey = `${'u'|'g'}:${string}${'R'|'W'|'M'}`
    if (!/^(u|g):.+[RWM]$/.test(entry)) {
      throw new Error(`Unique mock ContentUpsert: invalid fileAccess key "${entry}"`);
    }
    out.push(entry as FileAccessKey);
  }
  return out;
}

function paginatedContent(input: { variables: unknown; store: UniqueMockStore }): {
  paginatedContent: { nodes: unknown[]; totalCount: number };
} {
  const vars = expectObject(input.variables);
  const skip = typeof vars.skip === 'number' ? vars.skip : 0;
  const take = typeof vars.take === 'number' ? vars.take : 100;
  const where = (vars.where && typeof vars.where === 'object' ? vars.where : {}) as Record<
    string,
    unknown
  >;
  const keyFilter = (where.key && typeof where.key === 'object' ? where.key : {}) as Record<
    string,
    unknown
  >;

  const startsWith = typeof keyFilter.startsWith === 'string' ? keyFilter.startsWith : undefined;
  const keyIn =
    Array.isArray(keyFilter.in) && keyFilter.in.every((x) => typeof x === 'string')
      ? (keyFilter.in as string[])
      : undefined;

  const all = [...input.store.contentsById.values()];
  const filtered = all.filter((c) => {
    if (startsWith && !c.key.startsWith(startsWith)) return false;
    if (keyIn && !keyIn.includes(c.key)) return false;
    return true;
  });
  const nodes = filtered.slice(skip, skip + take);

  return {
    paginatedContent: {
      nodes: nodes.map((c) => ({
        id: c.id,
        fileAccess: c.fileAccess,
        key: c.key,
        ownerType: c.ownerType,
        ownerId: c.ownerId,
      })),
      totalCount: filtered.length,
    },
  };
}

function paginatedContentCount(input: { variables: unknown; store: UniqueMockStore }): {
  paginatedContent: { totalCount: number };
} {
  const result = paginatedContent({ variables: input.variables, store: input.store });
  return { paginatedContent: { totalCount: result.paginatedContent.totalCount } };
}

function changeFileAccesses(input: {
  variables: unknown;
  store: UniqueMockStore;
  mode: 'add' | 'remove';
}): { createFileAccessesForContents?: boolean; removeFileAccessesForContents?: boolean } {
  const vars = expectObject(input.variables);
  const fileAccesses = expectArray(vars.fileAccesses);

  for (const entry of fileAccesses) {
    const dto = expectObject(entry);
    const contentId = expectString(dto.contentId);
    const accessType = expectAccessType(dto.accessType);
    const entityType = expectEntityType(dto.entityType);
    const entityId = expectString(dto.entityId);
    const key = toFileAccessKey({ accessType, entityType, entityId });

    const content = input.store.contentsById.get(contentId);
    if (!content) continue;

    const current = new Set<string>(content.fileAccess);
    if (input.mode === 'add') current.add(key);
    else current.delete(key);
    content.fileAccess = [...current] as never;
  }

  return input.mode === 'add'
    ? { createFileAccessesForContents: true }
    : { removeFileAccessesForContents: true };
}

function contentUpdate(input: { variables: unknown; store: UniqueMockStore }): {
  contentUpdate: { id: string; ownerId: string; ownerType: string };
} {
  const vars = expectObject(input.variables);
  const contentId = expectString(vars.contentId);
  const content = input.store.contentsById.get(contentId);
  if (!content) {
    throw new Error(`Unique mock contentUpdate: content not found (id: ${contentId})`);
  }
  return {
    contentUpdate: { id: content.id, ownerId: content.ownerId, ownerType: content.ownerType },
  };
}

function contentDelete(input: { variables: unknown; store: UniqueMockStore }): {
  contentDelete: boolean;
} {
  const vars = expectObject(input.variables);
  const contentDeleteId = expectString(vars.contentDeleteId);
  const existing = input.store.contentsById.get(contentDeleteId);
  if (existing) {
    input.store.contentsById.delete(contentDeleteId);
    input.store.contentsByKey.delete(existing.key);
  }
  return { contentDelete: true };
}

function contentDeleteByContentIds(input: { variables: unknown; store: UniqueMockStore }): {
  contentDeleteByContentIds: Array<{ id: string }>;
} {
  const vars = expectObject(input.variables);
  const contentIds = expectArray(vars.contentIds).filter((x): x is string => typeof x === 'string');
  const deleted: Array<{ id: string }> = [];
  for (const id of contentIds) {
    const existing = input.store.contentsById.get(id);
    if (existing) {
      input.store.contentsById.delete(id);
      input.store.contentsByKey.delete(existing.key);
      deleted.push({ id });
    }
  }
  return { contentDeleteByContentIds: deleted };
}

function paginatedScope(input: { variables: unknown; store: UniqueMockStore }): {
  paginatedScope: { totalCount: number; nodes: unknown[] };
} {
  const vars = expectObject(input.variables);
  const skip = typeof vars.skip === 'number' ? vars.skip : 0;
  const take = typeof vars.take === 'number' ? vars.take : 100;
  const where = (vars.where && typeof vars.where === 'object' ? vars.where : {}) as Record<
    string,
    unknown
  >;

  const idEquals = readEqualsFilter(where.id);
  const nameEquals = readEqualsFilter(where.name);
  const parentIdEquals = where.parentId === null ? null : readEqualsFilter(where.parentId);

  const all = [...input.store.scopesById.values()];
  const filtered = all.filter((s) => {
    if (idEquals && s.id !== idEquals) return false;
    if (nameEquals && s.name !== nameEquals) return false;
    if (parentIdEquals === null && s.parentId !== null) return false;
    if (typeof parentIdEquals === 'string' && s.parentId !== parentIdEquals) return false;
    return true;
  });
  const nodes = filtered.slice(skip, skip + take);

  return {
    paginatedScope: {
      totalCount: filtered.length,
      nodes: nodes.map((s) => ({
        id: s.id,
        name: s.name,
        parentId: s.parentId,
        externalId: s.externalId,
      })),
    },
  };
}

function updateScope(input: { variables: unknown; store: UniqueMockStore }): {
  updateScope: { id: string; name: string; externalId: string | null };
} {
  const vars = expectObject(input.variables);
  const id = expectString(vars.id);
  const inputObj = expectObject(vars.input);
  const externalId = expectString(inputObj.externalId);

  const existing = input.store.scopesById.get(id);
  const updated = {
    id,
    name: existing?.name ?? 'RootScope',
    parentId: existing?.parentId ?? null,
    externalId,
    scopeAccess: existing?.scopeAccess,
  };
  input.store.scopesById.set(id, updated);

  return {
    updateScope: { id, name: updated.name, externalId: updated.externalId },
  };
}

function createOrDeleteScopeAccesses(input: {
  variables: unknown;
  store: UniqueMockStore;
  mode: 'add' | 'remove';
}): { createScopeAccesses?: boolean; deleteScopeAccesses?: boolean } {
  const vars = expectObject(input.variables);
  const scopeId = expectString(vars.scopeId);
  const scope = input.store.scopesById.get(scopeId);
  if (!scope) {
    return input.mode === 'add' ? { createScopeAccesses: true } : { deleteScopeAccesses: true };
  }

  const entries = expectArray(vars.scopeAccesses);
  const current = new Map<
    string,
    { entityId: string; entityType: UniqueEntityType; type: UniqueAccessType }
  >();
  for (const access of scope.scopeAccess ?? []) {
    current.set(`${access.entityType}:${access.entityId}:${access.type}`, access);
  }

  for (const entry of entries) {
    const dto = expectObject(entry);
    const entityId = expectString(dto.entityId);
    const entityType = expectEntityType(dto.entityType);
    const type = expectAccessType(dto.accessType);
    const key = `${entityType}:${entityId}:${type}`;
    if (input.mode === 'add') current.set(key, { entityId, entityType, type });
    else current.delete(key);
  }

  scope.scopeAccess = [...current.values()];
  input.store.scopesById.set(scopeId, scope);

  return input.mode === 'add' ? { createScopeAccesses: true } : { deleteScopeAccesses: true };
}

function getCurrentUser(input: { store: UniqueMockStore }): { me: { user: { id: string } } } {
  const first = input.store.usersById.values().next().value as { id?: string } | undefined;
  return { me: { user: { id: first?.id ?? 'unique-user-1' } } };
}

function listUsers(input: { store: UniqueMockStore }): {
  listUsers: { totalCount: number; nodes: Array<{ id: string; active: boolean; email: string }> };
} {
  const nodes = [...input.store.usersById.values()].map((u) => ({
    id: u.id,
    active: u.active ?? true,
    email: u.email ?? 'user@example.com',
  }));
  return { listUsers: { totalCount: nodes.length, nodes } };
}

function listGroups(input: { variables: unknown; store: UniqueMockStore }): {
  listGroups: unknown[];
} {
  const vars = expectObject(input.variables);
  const skip = typeof vars.skip === 'number' ? vars.skip : 0;
  const take = typeof vars.take === 'number' ? vars.take : 100;
  const where = (vars.where && typeof vars.where === 'object' ? vars.where : {}) as Record<
    string,
    unknown
  >;
  const externalIdStartsWith =
    where.externalId && typeof where.externalId === 'object'
      ? (where.externalId as Record<string, unknown>).startsWith
      : undefined;

  const nameEquals = readEqualsFilter(where.name);

  const all = [...input.store.groupsById.values()];
  const filtered = all.filter((g) => {
    if (
      typeof externalIdStartsWith === 'string' &&
      !g.externalId?.startsWith(externalIdStartsWith)
    ) {
      return false;
    }
    if (typeof nameEquals === 'string' && g.name !== nameEquals) {
      return false;
    }
    return true;
  });
  const nodes = filtered.slice(skip, skip + take);

  return {
    listGroups: nodes.map((g) => ({
      id: g.id,
      name: g.name,
      externalId: g.externalId,
      // Selection-set driven behavior isn't available in this mock engine; always returning members
      // avoids masking membership logic.
      members: g.members,
    })),
  };
}

function createGroup(input: { variables: unknown; store: UniqueMockStore }): {
  createGroup: { id: string; name: string; externalId: string | null };
} {
  const vars = expectObject(input.variables);
  const name = expectString(vars.name);
  const externalId = vars.externalId === null ? null : expectString(vars.externalId);
  const id = randomUUID();

  input.store.groupsById.set(id, { id, name, externalId, members: [] });
  return { createGroup: { id, name, externalId } };
}

function updateGroup(input: { variables: unknown; store: UniqueMockStore }): {
  updateGroup: { id: string; name: string; externalId: string | null };
} {
  const vars = expectObject(input.variables);
  const groupId = expectString(vars.groupId);
  const name = expectString(vars.name);

  const existing = input.store.groupsById.get(groupId);
  const next = {
    id: groupId,
    name,
    externalId: existing?.externalId ?? null,
    members: existing?.members ?? [],
  };
  input.store.groupsById.set(groupId, next);
  return { updateGroup: { id: next.id, name: next.name, externalId: next.externalId } };
}

function deleteGroup(input: { variables: unknown; store: UniqueMockStore }): {
  deleteGroup: { id: string };
} {
  const vars = expectObject(input.variables);
  const groupId = expectString(vars.groupId);
  input.store.groupsById.delete(groupId);
  return { deleteGroup: { id: groupId } };
}

function addGroupMembers(input: { variables: unknown; store: UniqueMockStore }): {
  addGroupMembers: unknown[];
} {
  const vars = expectObject(input.variables);
  const groupId = expectString(vars.groupId);
  const userIds = expectArray(vars.userIds).filter((x): x is string => typeof x === 'string');

  const group = input.store.groupsById.get(groupId);
  if (!group) return { addGroupMembers: [] };

  const current = new Set(group.members.map((m) => m.entityId));
  for (const id of userIds) current.add(id);
  group.members = [...current].map((id) => ({ entityId: id }));
  input.store.groupsById.set(groupId, group);

  return {
    addGroupMembers: userIds.map((userId) => ({ entityId: userId, groupId })),
  };
}

function removeGroupMember(input: { variables: unknown; store: UniqueMockStore }): {
  removeGroupMember: boolean;
} {
  const vars = expectObject(input.variables);
  const groupId = expectString(vars.groupId);
  const userId = expectString(vars.userId);

  const group = input.store.groupsById.get(groupId);
  if (!group) return { removeGroupMember: true };

  group.members = group.members.filter((m) => m.entityId !== userId);
  input.store.groupsById.set(groupId, group);
  return { removeGroupMember: true };
}

function readEqualsFilter(value: unknown): string | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const obj = value as Record<string, unknown>;
  return typeof obj.equals === 'string' ? obj.equals : undefined;
}

function expectObject(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object') {
    throw new Error('Expected variables to be an object');
  }
  return value as Record<string, unknown>;
}

function expectArray(value: unknown): unknown[] {
  if (!Array.isArray(value)) throw new Error('Expected array');
  return value;
}

function expectString(value: unknown): string {
  if (typeof value !== 'string') throw new Error('Expected string');
  return value;
}

function expectNumber(value: unknown): number {
  if (typeof value !== 'number') throw new Error('Expected number');
  return value;
}

function expectAccessType(value: unknown): UniqueAccessType {
  if (value !== 'READ' && value !== 'WRITE' && value !== 'MANAGE') {
    throw new Error('Expected UniqueAccessType');
  }
  return value;
}

function expectEntityType(value: unknown): UniqueEntityType {
  if (value !== 'USER' && value !== 'GROUP') {
    throw new Error('Expected UniqueEntityType');
  }
  return value;
}
