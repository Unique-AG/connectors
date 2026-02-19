import type { ContentUpdateResult, FileAccessInput, UniqueFile } from './files.types';

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
  // TODO: Check if we can avoid passing the scope id
  getIdsByScopeAndMetadataKey(
    scopeId: string,
    metadataKey: string,
    metadataValue: unknown,
  ): Promise<string[]>;
}
