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
  url?: string;
  baseUrl?: string;
}

export interface FileDiffItem {
  key: string;
  url: string;
  updatedAt: string;
  scopeStructure?: string;
}

export interface FileDiffRequest {
  basePath?: string;
  rootScopeId?: string;
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

export interface ZitadelLoginResponse {
  access_token: string;
  expires_in: number;
  token_type: string;
  id_token: string;
}
