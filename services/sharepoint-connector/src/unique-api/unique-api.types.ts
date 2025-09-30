import { NullableOption } from '@microsoft/microsoft-graph-types';

export interface ContentRegistrationRequest {
  key: string;
  title: string;
  mimeType: string;
  ownerType: string;
  scopeId: string;
  sourceOwnerType: string;
  sourceKind: string;
  sourceName: string;
}

export interface ContentRegistrationResponse {
  id: string;
  key: string;
  byteSize: number;
  mimeType: string;
  ownerType: string;
  ownerId: string;
  writeUrl: string;
  readUrl: string;
  createdAt: string;
  internallyStoredAt?: string;
  source: {
    kind: string;
  };
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
}

export interface FileDiffItem {
  id: string | undefined;
  name: NullableOption<string> | undefined;
  url: NullableOption<string> | undefined;
  updatedAt: NullableOption<string> | undefined;
  key: NullableOption<string> | undefined;
}

export interface FileDiffRequest {
  basePath: string;
  partialKey: string;
  sourceKind: string;
  sourceName: string;
  fileList: FileDiffItem[];
  scope: string;
}

export interface FileDiffResponse {
  newAndUpdatedFiles: string[];
  deletedFiles: string[];
  movedFiles: string[];
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

export interface IngestionApiResponseWrapper {
  contentUpsert: IngestionApiResponse;
}

export interface ApiResponse<T> {
  data: T;
}
