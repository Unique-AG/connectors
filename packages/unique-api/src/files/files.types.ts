import type { UniqueAccessType, UniqueEntityType } from '../types';

export type FileAccessModifier = 'R' | 'W' | 'M';

export type FileGranteeType = 'u' | 'g';

export type FileAccessKey = `${FileGranteeType}:${string}${FileAccessModifier}`;

export interface UniqueFile {
  id: string;
  fileAccess: FileAccessKey[];
  key: string;
  ownerType: string;
  ownerId: string;
  byteSize: number;
  metadata: Record<string, string> | null;
}

export interface FileAccessInput {
  contentId: string;
  accessType: UniqueAccessType;
  entityId: string;
  entityType: UniqueEntityType;
}

export interface ContentUpdateResult {
  id: string;
  ownerId: string;
  ownerType: string;
}
