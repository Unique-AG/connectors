export interface ContentRegistrationRequest {
  key: string;
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
  id: string;
  name: string;
  url: string;
  updatedAt: string;
  key: string;
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
