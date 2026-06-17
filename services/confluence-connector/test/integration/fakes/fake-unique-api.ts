import assert from 'node:assert';
import { randomUUID } from 'node:crypto';
import type {
  ContentRegistrationRequest,
  FileDiffItem,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionConfig,
  IngestionFinalizationRequest,
  Scope,
  ScopeAccess,
  UniqueApiClient,
  UniqueFile,
} from '@unique-ag/unique-api';
import { IngestionState } from '@unique-ag/unique-api';
import { mapValues } from 'remeda';
import type { ScenarioUnique } from '../scenario/scenario.types';

const FAKE_BLOB_HOST = 'https://fake-blob.local';

interface PendingUpload {
  contentId: string;
  key: string;
}

export interface ScopeWithPath extends Scope {
  path: string;
}

export interface StoredFile extends UniqueFile {
  mimeType: string;
  body?: Buffer;
  updatedAt: string;
  ingestionConfig: IngestionConfig | null;
}

/**
 * Stateful in-memory UniqueApiClient.
 *
 * Implements the production interface. Holds:
 * - a scope tree keyed by id, with parent and externalId
 * - a file table keyed by id and indexed by key
 * - pending uploads keyed by writeUrl token, settled by FakeBlobStorage on PUT
 *
 * Only methods exercised by the synchronization flow are implemented.
 * Unused methods throw to make accidental dependence visible.
 */
export class FakeUniqueApi implements UniqueApiClient {
  public readonly auth: UniqueApiClient['auth'];
  public readonly scopes: UniqueApiClient['scopes'];
  public readonly files: UniqueApiClient['files'];
  public readonly users: UniqueApiClient['users'];
  public readonly groups: UniqueApiClient['groups'];
  public readonly ingestion: UniqueApiClient['ingestion'];
  public readonly content: UniqueApiClient['content'];

  private readonly scopesById = new Map<string, Scope>();
  private readonly filesById = new Map<string, StoredFile>();
  private readonly pendingUploads = new Map<string, PendingUpload>();

  public constructor(initial: ScenarioUnique) {
    for (const scope of initial.scopes) {
      this.scopesById.set(scope.id, { ...scope });
    }
    for (const file of initial.files) {
      this.filesById.set(file.id, {
        id: file.id,
        key: file.key,
        byteSize: file.byteSize,
        mimeType: file.mimeType,
        ownerType: 'SCOPE',
        ownerId: file.scopeId ?? 'unknown',
        fileAccess: [],
        expiresAt: null,
        ingestionState: IngestionState.Finished,
        metadata: file.metadata ?? null,
        body: file.body,
        updatedAt: file.updatedAt,
        ingestionConfig: null,
      });
    }

    this.auth = { getToken: async () => 'fake-token' };
    this.scopes = this.buildScopesFacade();
    this.files = this.buildFilesFacade();
    this.users = {
      listAll: notImplemented('users.listAll'),
      findByEmail: notImplemented('users.findByEmail'),
      getCurrentId: async () => initial.currentUserId,
    };
    this.groups = this.buildUnusedGroupsFacade();
    this.ingestion = this.buildIngestionFacade();
    this.content = this.buildUnusedContentFacade();
  }

  /** FakeBlobStorage calls this when an upload PUT against the writeUrl arrives. */
  public completeUpload(uploadToken: string, body: Buffer): { matched: boolean } {
    const pending = this.pendingUploads.get(uploadToken);
    if (!pending) {
      return { matched: false };
    }
    const file = this.filesById.get(pending.contentId);
    if (file) {
      file.body = body;
      file.byteSize = body.byteLength;
    }
    this.pendingUploads.delete(uploadToken);
    return { matched: true };
  }

  public listScopes(): ScopeWithPath[] {
    const scopes = [...this.scopesById.values()];
    return scopes.map((scope) => ({ ...scope, path: this.resolveScopePath(scope) }));
  }

  private resolveScopePath(scope: Scope): string {
    const segments: string[] = [];
    let current: Scope | undefined = scope;
    while (current) {
      segments.unshift(current.name);
      current = current.parentId ? this.scopesById.get(current.parentId) : undefined;
    }
    return `/${segments.join('/')}`;
  }

  public listFiles(): StoredFile[] {
    return [...this.filesById.values()];
  }

  private buildScopesFacade(): UniqueApiClient['scopes'] {
    return {
      createFromPaths: async (paths) => {
        const created: Scope[] = [];
        for (const path of paths) {
          created.push(this.upsertPath(path));
        }
        return created;
      },
      getById: async (id) => this.scopesById.get(id) ?? null,
      getByExternalId: async (externalId) =>
        [...this.scopesById.values()].find((scope) => scope.externalId === externalId) ?? null,
      getByExternalIds: notImplemented('scopes.getByExternalIds'),
      updateExternalId: async (scopeId, externalId) => {
        const scope = this.requireScope(scopeId);
        const conflicting = [...this.scopesById.values()].find(
          (s) => s.id !== scopeId && externalId !== null && s.externalId === externalId,
        );
        assert.ok(
          !conflicting,
          `External id "${externalId}" is already taken by scope ${conflicting?.id}`,
        );
        scope.externalId = externalId;
        return { id: scope.id, externalId: scope.externalId };
      },
      updateParent: notImplemented('scopes.updateParent'),
      bulkMove: async (scopeIds, targetScopeId) => {
        for (const scopeId of scopeIds) {
          const scope = this.requireScope(scopeId);
          scope.parentId = targetScopeId;
        }
        return {
          scopeIds,
          asyncMetadataRebuild: false,
          jobId: null,
          affectedFiles: null,
          message: null,
        };
      },
      listChildren: async (parentId) =>
        [...this.scopesById.values()].filter((scope) => scope.parentId === parentId),
      createAccesses: async (_scopeId: string, _accesses: ScopeAccess[]) => {
        // Called during sync, but permissions are not modeled in the fake, so no-op.
      },
      deleteAccesses: notImplemented('scopes.deleteAccesses'),
      delete: async (scopeId) => {
        const scope = this.scopesById.get(scopeId);
        if (!scope) {
          return { successFolders: [], failedFolders: [] };
        }
        this.scopesById.delete(scopeId);
        return {
          successFolders: [{ id: scope.id, name: scope.name, path: scope.name }],
          failedFolders: [],
        };
      },
    };
  }

  private buildFilesFacade(): UniqueApiClient['files'] {
    return {
      getByKeys: async (keys) => {
        const set = new Set(keys);
        return [...this.filesById.values()].filter((f) => set.has(f.key));
      },
      getByKeyPrefix: notImplemented('files.getByKeyPrefix'),
      getCountByKeyPrefix: async (keyPrefix) =>
        [...this.filesById.values()].filter((f) => f.key.startsWith(keyPrefix)).length,
      move: notImplemented('files.move'),
      delete: async (contentId) => {
        return this.filesById.delete(contentId);
      },
      deleteByIds: async (contentIds) => {
        let deleted = 0;
        for (const id of contentIds) {
          if (this.filesById.delete(id)) {
            deleted++;
          }
        }
        return { deleted, failed: contentIds.length - deleted };
      },
      deleteByKeyPrefix: async (keyPrefix) => {
        const matching = [...this.filesById.values()].filter((f) => f.key.startsWith(keyPrefix));
        for (const file of matching) {
          this.filesById.delete(file.id);
        }
        return matching.length;
      },
      addAccesses: notImplemented('files.addAccesses'),
      removeAccesses: notImplemented('files.removeAccesses'),
      getContentIdsByScope: async (scopeId: string) =>
        [...this.filesById.values()].filter((f) => f.ownerId === scopeId).map((f) => f.id),
      getFileKeysByScopeId: notImplemented('files.getFileKeysByScopeId'),
      getIdsByScopeAndMetadataKey: notImplemented('files.getIdsByScopeAndMetadataKey'),
      getIdsByScope: notImplemented('files.getIdsByScope'),
    };
  }

  private buildIngestionFacade(): UniqueApiClient['ingestion'] {
    return {
      registerContent: async (request) => this.registerContent(request),
      finalizeIngestion: async (request) => this.finalizeIngestion(request),
      performFileDiff: async (fileList, partialKey, _sourceKind, _sourceName) =>
        this.performFileDiff(fileList, partialKey),
      update: notImplemented('ingestion.update'),
      getIngestionStats: notImplemented('ingestion.getIngestionStats'),
    };
  }

  private buildUnusedGroupsFacade(): UniqueApiClient['groups'] {
    return {
      listByExternalIdPrefix: notImplemented('groups.listByExternalIdPrefix'),
      create: notImplemented('groups.create'),
      update: notImplemented('groups.update'),
      delete: notImplemented('groups.delete'),
      addMembers: notImplemented('groups.addMembers'),
      removeMembers: notImplemented('groups.removeMembers'),
    };
  }

  private buildUnusedContentFacade(): UniqueApiClient['content'] {
    return {
      search: notImplemented('content.search'),
      getContentById: notImplemented('content.getContentById'),
    };
  }

  private upsertPath(path: string): Scope {
    const segments = path.split('/').filter((segment) => segment.length > 0);
    let parentId: string | null = null;
    let current: Scope | null = null;

    for (const segment of segments) {
      const existing = [...this.scopesById.values()].find(
        (scope) => scope.parentId === parentId && scope.name === segment,
      );
      if (existing) {
        current = existing;
        parentId = existing.id;
        continue;
      }
      const created: Scope = {
        id: `scope-${randomUUID()}`,
        name: segment,
        parentId,
        externalId: null,
      };
      this.scopesById.set(created.id, created);
      current = created;
      parentId = created.id;
    }

    assert.ok(current, `Cannot create scope from empty path "${path}"`);
    return current;
  }

  private registerContent(request: ContentRegistrationRequest): IngestionApiResponse {
    const existing = [...this.filesById.values()].find((f) => f.key === request.key);
    const id = existing?.id ?? `content-${randomUUID()}`;
    const uploadToken = randomUUID();
    const writeUrl = `${FAKE_BLOB_HOST}/blob/${uploadToken}`;
    const readUrl = `${FAKE_BLOB_HOST}/read/${uploadToken}`;

    const file: StoredFile = {
      id,
      key: request.key,
      byteSize: request.byteSize,
      mimeType: request.mimeType,
      ownerType: request.ownerType,
      ownerId: request.scopeId,
      fileAccess: request.fileAccess ?? [],
      expiresAt: null,
      ingestionState: IngestionState.Queued,
      metadata: stringifyMetadata(request.metadata),
      body: undefined,
      updatedAt: new Date().toISOString(),
      ingestionConfig: request.ingestionConfig ?? null,
    };
    this.filesById.set(id, file);
    this.pendingUploads.set(uploadToken, { contentId: id, key: request.key });

    return {
      id,
      key: request.key,
      byteSize: request.byteSize,
      mimeType: request.mimeType,
      ownerType: request.ownerType,
      ownerId: request.scopeId,
      writeUrl,
      readUrl,
      createdAt: new Date().toISOString(),
      internallyStoredAt: request.storeInternally ? new Date().toISOString() : null,
      source: { kind: request.sourceKind, name: request.sourceName },
    };
  }

  private finalizeIngestion(request: IngestionFinalizationRequest): { id: string } {
    const file = [...this.filesById.values()].find((f) => f.key === request.key);
    assert.ok(file, `Cannot finalize unknown key "${request.key}"`);
    file.ingestionState = IngestionState.Finished;
    if (request.metadata) {
      file.metadata = stringifyMetadata(request.metadata);
    }
    return { id: file.id };
  }

  private performFileDiff(fileList: FileDiffItem[], partialKey: string): FileDiffResponse {
    const submitted = new Map(fileList.map((item) => [item.key, item]));
    const prefix = `${partialKey}/`;

    // The diff is scoped to a single partial key, mirroring Unique's per-space
    // file-diff: only content stored under this partial key is compared against
    // the submitted items. Content under other partial keys is not considered,
    // so a page that exists under a different space is simply "new" to this
    // space (a cross-space move surfaces as new-here plus deleted-there, not as
    // a single move).
    const existingByItemId = new Map<string, StoredFile>();
    for (const file of this.filesById.values()) {
      if (file.key.startsWith(prefix)) {
        const itemId = file.key.slice(file.key.lastIndexOf('/') + 1);
        existingByItemId.set(itemId, file);
      }
    }

    const newFiles: string[] = [];
    const updatedFiles: string[] = [];
    const deletedFiles: string[] = [];

    for (const [itemId, item] of submitted) {
      const existing = existingByItemId.get(itemId);
      if (!existing) {
        newFiles.push(itemId);
        continue;
      }
      if (existing.updatedAt < item.updatedAt) {
        updatedFiles.push(itemId);
      }
    }

    for (const itemId of existingByItemId.keys()) {
      if (!submitted.has(itemId)) {
        deletedFiles.push(itemId);
      }
    }

    // movedFiles is always empty: Confluence keys are space-scoped, so Unique's
    // per-space diff never reports a page as moved (it is new in one space and
    // deleted in the other).
    return { newFiles, updatedFiles, movedFiles: [], deletedFiles };
  }

  private requireScope(scopeId: string): Scope {
    const scope = this.scopesById.get(scopeId);
    assert.ok(scope, `Unknown scope: ${scopeId}`);
    return scope;
  }
}

// Unique stores metadata as a flat string map, so coerce each value on its own:
// strings stay as-is, everything else (e.g. the confluenceLabels array) is
// JSON-encoded.
function stringifyMetadata(
  metadata: Record<string, unknown> | undefined,
): Record<string, string> | null {
  if (!metadata) {
    return null;
  }
  return mapValues(metadata, (value) =>
    typeof value === 'string' ? value : JSON.stringify(value),
  );
}

function notImplemented<TArgs extends unknown[], TResult>(
  name: string,
): (...args: TArgs) => Promise<TResult> {
  return () => {
    throw new Error(`FakeUniqueApi.${name} is not implemented for integration tests.`);
  };
}
