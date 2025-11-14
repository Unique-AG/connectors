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