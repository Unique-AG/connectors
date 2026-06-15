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
import type { ScenarioUnique } from '../scenario/scenario.types';

const FAKE_BLOB_HOST = 'https://fake-blob.local';

interface PendingUpload {
  contentId: string;
  key: string;
}

export interface StoredFile extends UniqueFile {
  mimeType: string;
  body?: Buffer;
  updatedAt: string;
  /** Captured `ingestionConfig` from the most recent registerContent call (e.g. `jpgReadMode`). */
  ingestionConfig: IngestionConfig | null;
}

interface FailureMap {
  registerContent: Map<string, Error>;
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
  private readonly failures: FailureMap = {
    registerContent: new Map(),
  };
  /**
   * Item keys the next `performFileDiff` should classify as `movedFiles`.
   *
   * Whether a file is "moved" is decided server-side by Unique (same logical
   * resource re-keyed to a new location), so the per-`partialKey` diff this fake
   * reimplements cannot derive it on its own. This seam lets a test inject that
   * server verdict, mirroring the `failOn*` injection hooks, so the connector's
   * handling of moved files can be exercised end-to-end.
   */
  private readonly movedItemKeys = new Set<string>();

  public constructor(private readonly initial: ScenarioUnique) {
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
      getCurrentId: async () => this.initial.currentUserId,
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

  public listScopes(): Scope[] {
    return [...this.scopesById.values()];
  }

  public listFiles(): StoredFile[] {
    return [...this.filesById.values()];
  }

  // ─── Failure-injection hooks ─────────────────────────────────────────────────

  public failOnRegisterContent(key: string, error: Error): void {
    this.failures.registerContent.set(key, error);
  }

  /**
   * Make the next `performFileDiff` report the given item keys as `movedFiles`
   * instead of new/updated/deleted. See {@link movedItemKeys} for why this is
   * injected rather than derived.
   */
  public simulateMovedFiles(itemKeys: string[]): void {
    for (const key of itemKeys) {
      this.movedItemKeys.add(key);
    }
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
      getByExternalId: notImplemented('scopes.getByExternalId'),
      getByExternalIds: notImplemented('scopes.getByExternalIds'),
      updateExternalId: async (scopeId, externalId) => {
        const scope = this.requireScope(scopeId);
        const conflicting = [...this.scopesById.values()].find(
          (s) => s.id !== scopeId && externalId !== null && s.externalId === externalId,
        );
        if (conflicting) {
          throw new Error(
            `External id "${externalId}" is already taken by scope ${conflicting.id}`,
          );
        }
        scope.externalId = externalId;
        return { id: scope.id, externalId: scope.externalId };
      },
      updateParent: notImplemented('scopes.updateParent'),
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

    if (!current) {
      throw new Error(`Cannot create scope from empty path "${path}"`);
    }
    return current;
  }

  private registerContent(request: ContentRegistrationRequest): IngestionApiResponse {
    const failure = this.failures.registerContent.get(request.key);
    if (failure) {
      throw failure;
    }
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
    if (!file) {
      throw new Error(`Cannot finalize unknown key "${request.key}"`);
    }
    file.ingestionState = IngestionState.Finished;
    if (request.metadata) {
      file.metadata = stringifyMetadata(request.metadata);
    }
    return { id: file.id };
  }

  private performFileDiff(fileList: FileDiffItem[], partialKey: string): FileDiffResponse {
    const submitted = new Map(fileList.map((item) => [item.key, item]));
    const existing = [...this.filesById.values()].filter((f) => f.key.startsWith(`${partialKey}/`));

    const newFiles: string[] = [];
    const updatedFiles: string[] = [];
    const movedFiles: string[] = [];
    const deletedFiles: string[] = [];

    const existingByItemKey = new Map<string, (typeof existing)[number]>();
    for (const file of existing) {
      const itemKey = file.key.slice(partialKey.length + 1);
      existingByItemKey.set(itemKey, file);
    }

    for (const [key, item] of submitted) {
      if (this.movedItemKeys.has(key)) {
        movedFiles.push(key);
        continue;
      }
      const found = existingByItemKey.get(key);
      if (!found) {
        newFiles.push(key);
        continue;
      }
      if (found.updatedAt < item.updatedAt) {
        updatedFiles.push(key);
      }
    }

    for (const [key] of existingByItemKey) {
      if (this.movedItemKeys.has(key)) {
        // A moved file is relocated server-side, never deleted.
        if (!submitted.has(key)) {
          movedFiles.push(key);
        }
        continue;
      }
      if (!submitted.has(key)) {
        deletedFiles.push(key);
      }
    }

    return { newFiles, updatedFiles, movedFiles, deletedFiles };
  }

  private requireScope(scopeId: string): Scope {
    const scope = this.scopesById.get(scopeId);
    if (!scope) {
      throw new Error(`Unknown scope: ${scopeId}`);
    }
    return scope;
  }
}

function stringifyMetadata(
  metadata: Record<string, unknown> | undefined,
): Record<string, string> | null {
  if (!metadata) {
    return null;
  }
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(metadata)) {
    result[key] = typeof value === 'string' ? value : JSON.stringify(value);
  }
  return result;
}

function notImplemented<TArgs extends unknown[], TResult>(
  name: string,
): (...args: TArgs) => Promise<TResult> {
  return () => {
    throw new Error(`FakeUniqueApi.${name} is not implemented for integration tests.`);
  };
}
