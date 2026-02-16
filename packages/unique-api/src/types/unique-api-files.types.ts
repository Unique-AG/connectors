import type {
  ContentUpdateResult,
  FileAccessInput,
  UniqueFile,
} from "../files/files.types";

export interface UniqueApiFiles {
  getByKeys(keys: string[]): Promise<UniqueFile[]>;
  getByKeyPrefix(keyPrefix: string): Promise<UniqueFile[]>;
  getCountByKeyPrefix(keyPrefix: string): Promise<number>;
  move(
    contentId: string,
    newOwnerId: string,
    newUrl: string,
  ): Promise<ContentUpdateResult>;
  delete(contentId: string): Promise<boolean>;
  deleteByIds(contentId: string[]): Promise<number>;
  deleteByKeyPrefix(keyPrefix: string): Promise<number>;
  addAccesses(
    scopeId: string,
    fileAccesses: FileAccessInput[],
  ): Promise<number>;
  removeAccesses(
    scopeId: string,
    fileAccesses: FileAccessInput[],
  ): Promise<number>;
}
