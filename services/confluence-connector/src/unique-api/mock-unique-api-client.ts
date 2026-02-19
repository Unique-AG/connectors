import type pino from 'pino';
import type {
  ContentRegistrationRequest,
  ContentUpdateMetadataMutationInput,
  ContentUpdateMetadataResponse,
  ContentUpdateResult,
  FileAccessInput,
  FileDiffItem,
  FileDiffResponse,
  IngestionApiResponse,
  IngestionFinalizationRequest,
  UniqueFile,
  UniqueFilesFacade,
  UniqueIngestionFacade,
} from './types';
import { UniqueApiClient } from './types';

function notImplemented(facadeName: string): never {
  throw new Error(`UniqueApiClient.${facadeName} is not implemented in mock`);
}

class MockIngestionFacade implements UniqueIngestionFacade {
  public constructor(private readonly logger: pino.Logger) {}

  public async performFileDiff(
    fileList: FileDiffItem[],
    partialKey: string,
    sourceKind: string,
    sourceName: string,
  ): Promise<FileDiffResponse> {
    this.logger.debug(
      { fileCount: fileList.length, partialKey, sourceKind, sourceName },
      'performFileDiff called',
    );
    return {
      newFiles: fileList.map((f) => f.key),
      updatedFiles: [],
      movedFiles: [],
      deletedFiles: [],
    };
  }

  public async registerContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse> {
    this.logger.debug({ key: request.key, title: request.title }, 'registerContent called');
    return {
      id: `mock-id-${request.key}`,
      key: request.key,
      byteSize: request.byteSize,
      mimeType: request.mimeType,
      ownerType: request.ownerType,
      ownerId: 'mock-owner-id',
      writeUrl: `https://mock-storage.example.com/write/${request.key}`,
      readUrl: `https://mock-storage.example.com/read/${request.key}`,
      createdAt: new Date().toISOString(),
      internallyStoredAt: null,
      source: { kind: request.sourceKind, name: request.sourceName },
    };
  }

  public async finalizeIngestion(request: IngestionFinalizationRequest): Promise<{ id: string }> {
    this.logger.debug({ key: request.key, title: request.title }, 'finalizeIngestion called');
    return { id: 'mock-content-id' };
  }

  public async updateMetadata(
    request: ContentUpdateMetadataMutationInput,
  ): Promise<ContentUpdateMetadataResponse> {
    this.logger.debug({ contentId: request.contentId }, 'updateMetadata called');
    return { id: request.contentId, metadata: request.metadata };
  }
}

class MockFilesFacade implements UniqueFilesFacade {
  public constructor(private readonly logger: pino.Logger) {}

  public async getByKeys(keys: string[]): Promise<UniqueFile[]> {
    this.logger.debug({ keyCount: keys.length }, 'getByKeys called');
    return [];
  }

  public async getByKeyPrefix(keyPrefix: string): Promise<UniqueFile[]> {
    this.logger.debug({ keyPrefix }, 'getByKeyPrefix called');
    return [];
  }

  public async getCountByKeyPrefix(keyPrefix: string): Promise<number> {
    this.logger.debug({ keyPrefix }, 'getCountByKeyPrefix called');
    return 0;
  }

  public async move(
    contentId: string,
    newOwnerId: string,
    newUrl: string,
  ): Promise<ContentUpdateResult> {
    this.logger.debug({ contentId, newOwnerId, newUrl }, 'move called');
    return { id: contentId, key: `mock-key-${contentId}` };
  }

  public async delete(contentId: string): Promise<boolean> {
    this.logger.debug({ contentId }, 'delete called');
    return true;
  }

  public async deleteByIds(contentIds: string[]): Promise<number> {
    this.logger.debug({ count: contentIds.length }, 'deleteByIds called');
    return contentIds.length;
  }

  public async deleteByKeyPrefix(keyPrefix: string): Promise<number> {
    this.logger.debug({ keyPrefix }, 'deleteByKeyPrefix called');
    return 0;
  }

  public async addAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number> {
    this.logger.debug({ scopeId, count: fileAccesses.length }, 'addAccesses called');
    return fileAccesses.length;
  }

  public async removeAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number> {
    this.logger.debug({ scopeId, count: fileAccesses.length }, 'removeAccesses called');
    return fileAccesses.length;
  }

  public async getIdsByScopeAndMetadataKey(
    scopeId: string,
    metadataKey: string,
    metadataValue: unknown,
  ): Promise<string[]> {
    this.logger.debug(
      { scopeId, metadataKey, metadataValue },
      'getIdsByScopeAndMetadataKey called',
    );
    return [];
  }
}

export class MockUniqueApiClient extends UniqueApiClient {
  public readonly ingestion: UniqueIngestionFacade;
  public readonly files: UniqueFilesFacade;

  public constructor(logger: pino.Logger) {
    super();
    const ingestionLogger = logger.child({ facade: 'ingestion' });
    const filesLogger = logger.child({ facade: 'files' });
    this.ingestion = new MockIngestionFacade(ingestionLogger);
    this.files = new MockFilesFacade(filesLogger);
  }

  public get auth(): never {
    return notImplemented('auth');
  }

  public get scopes(): never {
    return notImplemented('scopes');
  }

  public get users(): never {
    return notImplemented('users');
  }

  public get groups(): never {
    return notImplemented('groups');
  }
}
