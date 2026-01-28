import { ContentUpsertMutationInput } from '../../src/unique-api/unique-file-ingestion/unique-file-ingestion.consts';
import { FileDiffRequest, FileDiffResponse } from '../../src/unique-api/unique-file-ingestion/unique-file-ingestion.types';
import { UniqueFileAccessInput } from '../../src/unique-api/unique-files/unique-files.types';

export interface FakeContent {
  id: string;
  key: string;
  title: string;
  mimeType: string;
  byteSize: number;
  updatedAt: string;
  access: Set<string>;
  metadata: Record<string, any>;
  ownerId: string;
  ownerType: string;
}

export class FakeUniqueRegistry {
  private contents = new Map<string, FakeContent>();
  private idCounter = 0;

  public clear(): void {
    this.contents.clear();
    this.idCounter = 0;
  }

  public getFiles(): FakeContent[] {
    return Array.from(this.contents.values());
  }

  public getFile(key: string): FakeContent | undefined {
    return this.contents.get(key);
  }

  public getFileBySpId(id: string): FakeContent | undefined {
    return Array.from(this.contents.values()).find((f) => f.key.endsWith(`/${id}`));
  }

  public deleteFile(key: string): void {
    this.contents.delete(key);
  }

  /**
   * Mock for Unique Ingestion Service /file-diff endpoint
   */
  public handleFileDiff(request: FileDiffRequest): FileDiffResponse {
    const newFiles: string[] = [];
    const updatedFiles: string[] = [];
    const movedFiles: string[] = [];
    const deletedFiles: string[] = [];

    const requestKeys = new Set(request.fileList.map((f) => f.key));

    for (const item of request.fileList) {
      const existing = this.getFileBySpId(item.key);
      if (!existing) {
        newFiles.push(item.key);
      } else if (existing.updatedAt !== item.updatedAt) {
        updatedFiles.push(item.key);
      }
    }

    // Identify deleted files (in registry with same partialKey/source prefix, but not in current request)
    for (const [fullKey, content] of this.contents.entries()) {
      const relativeId = fullKey.split('/').pop()!;
      if (fullKey.startsWith(`${request.partialKey}/`) && !requestKeys.has(relativeId)) {
        deletedFiles.push(relativeId);
      }
    }

    return {
      newFiles,
      updatedFiles,
      movedFiles,
      deletedFiles,
    };
  }

  /**
   * Mock for Unique Ingestion GraphQL ContentUpsert mutation
   */
  public handleContentUpsert(input: ContentUpsertMutationInput): any {
    const { key, title, mimeType, byteSize, metadata, fileAccess } = input.input;
    const existing = this.contents.get(key);

    const id = existing?.id || `content-${++this.idCounter}`;
    const access = new Set(existing?.access || []);
    if (fileAccess) {
      for (const a of fileAccess) access.add(a);
    }

    const content: FakeContent = {
      id,
      key,
      title,
      mimeType,
      byteSize: byteSize || 0,
      updatedAt: new Date().toISOString(),
      access,
      metadata: metadata || {},
      ownerId: 'fake-owner-id',
      ownerType: input.sourceOwnerType,
    };

    this.contents.set(key, content);

    return {
      id,
      key,
      title,
      byteSize: content.byteSize,
      mimeType,
      ownerType: input.sourceOwnerType,
      ownerId: 'fake-owner-id',
      writeUrl: `https://upload.example.com/${id}?key=${encodeURIComponent(key)}`,
      readUrl: `https://content.example.com/${id}`,
      createdAt: new Date().toISOString(),
      internallyStoredAt: null,
      source: {
        kind: input.sourceKind,
        name: input.sourceName,
      },
    };
  }

  /**
   * Mock for Unique Scope Management GraphQL createFileAccessesForContents mutation
   */
  public handleCreateFileAccesses(fileAccesses: UniqueFileAccessInput[]): boolean {
    for (const accessInput of fileAccesses) {
      const content = Array.from(this.contents.values()).find((c) => c.id === accessInput.contentId);
      if (content) {
        const modifier =
          accessInput.accessType === 'READ' ? 'R' : accessInput.accessType === 'WRITE' ? 'W' : 'M';
        const granteeType = accessInput.entityType === 'USER' ? 'u' : 'g';
        const accessKey = `${granteeType}:${accessInput.entityId}${modifier}`;
        content.access.add(accessKey);
      }
    }
    return true;
  }

  /**
   * Mock for Unique Scope Management GraphQL removeFileAccessesForContents mutation
   */
  public handleRemoveFileAccesses(fileAccesses: UniqueFileAccessInput[]): boolean {
    for (const accessInput of fileAccesses) {
      const content = Array.from(this.contents.values()).find((c) => c.id === accessInput.contentId);
      if (content) {
        const modifier =
          accessInput.accessType === 'READ' ? 'R' : accessInput.accessType === 'WRITE' ? 'W' : 'M';
        const granteeType = accessInput.entityType === 'USER' ? 'u' : 'g';
        content.access.delete(`${granteeType}:${accessInput.entityId}${modifier}`);
      }
    }
    return true;
  }
}
