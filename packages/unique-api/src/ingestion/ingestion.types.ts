import type { FileAccessKey } from '../files/files.types';

export interface AuthorMetadata {
  email: string;
  displayName: string;
  id: string;
}

export type ContentMetadataValue =
  | string
  | number
  | boolean
  | null
  | AuthorMetadata
  | ContentMetadataValue[];

export interface ContentMetadata {
  [key: string]: ContentMetadataValue;
}

export interface ContentRegistrationRequest {
  key: string;
  title: string;
  mimeType: string;
  ownerType: string;
  scopeId: string;
  sourceOwnerType: string;
  sourceKind: string;
  sourceName: string;
  url?: string;
  baseUrl?: string;
  byteSize: number;
  fileAccess?: FileAccessKey[];
  metadata: ContentMetadata;
  storeInternally: boolean;
}

export interface IngestionFinalizationRequest {
  key: string;
  title: string;
  mimeType: string;
  ownerType: string;
  byteSize: number;
  scopeId: string;
  sourceOwnerType: string;
  sourceName: string;
  sourceKind: string;
  fileUrl: string;
  url?: string;
  baseUrl?: string;
  metadata?: ContentMetadata;
  storeInternally: boolean;
}

export interface IngestionApiResponse {
  id: string;
  key: string;
  byteSize: number;
  mimeType: string;
  ownerType: string;
  ownerId: string;
  writeUrl: string;
  readUrl: string;
  createdAt: string;
  internallyStoredAt: string | null;
  source: string;
}

export interface FileDiffItem {
  key: string;
  url: string;
  updatedAt: string;
}

export interface FileDiffRequest {
  partialKey: string;
  sourceKind: string;
  sourceName: string;
  fileList: FileDiffItem[];
}

export interface FileDiffResponse {
  newFiles: string[];
  updatedFiles: string[];
  movedFiles: string[];
  deletedFiles: string[];
}
