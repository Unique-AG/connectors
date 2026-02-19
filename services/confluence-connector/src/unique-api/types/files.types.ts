export interface UniqueFile {
  id: string;
  key: string;
  ownerType: string;
  ownerId: string;
  byteSize: number;
  metadata: Record<string, unknown>;
  fileAccess: Array<{ type: string; entityId: string; entityType: string }>;
}

export interface FileAccessInput {
  entityId: string;
  entityType: string;
}

export interface ContentUpdateResult {
  id: string;
  key: string;
}

export interface UniqueFilesFacade {
  getByKeys(keys: string[]): Promise<UniqueFile[]>;
  getByKeyPrefix(keyPrefix: string): Promise<UniqueFile[]>;
  getCountByKeyPrefix(keyPrefix: string): Promise<number>;
  move(contentId: string, newOwnerId: string, newUrl: string): Promise<ContentUpdateResult>;
  delete(contentId: string): Promise<boolean>;
  deleteByIds(contentId: string[]): Promise<number>;
  deleteByKeyPrefix(keyPrefix: string): Promise<number>;
  addAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number>;
  removeAccesses(scopeId: string, fileAccesses: FileAccessInput[]): Promise<number>;
  getIdsByScopeAndMetadataKey(
    scopeId: string,
    metadataKey: string,
    metadataValue: unknown,
  ): Promise<string[]>;
}
