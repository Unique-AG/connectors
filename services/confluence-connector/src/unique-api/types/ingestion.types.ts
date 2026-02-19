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
  byteSize?: number;
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
  source: { kind: string; name: string };
}

export interface FileDiffItem {
  key: string;
  url: string;
  updatedAt: string;
}

export interface FileDiffResponse {
  newFiles: string[];
  updatedFiles: string[];
  movedFiles: string[];
  deletedFiles: string[];
}

export interface ContentUpdateMetadataMutationInput {
  contentId: string;
  metadata: ContentMetadata;
}

export interface ContentUpdateMetadataResponse {
  id: string;
  metadata: ContentMetadata;
}

export type FileAccessKey = `${string}:${string}${string}`;

export interface UniqueIngestionFacade {
  registerContent(request: ContentRegistrationRequest): Promise<IngestionApiResponse>;
  finalizeIngestion(request: IngestionFinalizationRequest): Promise<{ id: string }>;
  performFileDiff(
    fileList: FileDiffItem[],
    partialKey: string,
    sourceKind: string,
    sourceName: string,
  ): Promise<FileDiffResponse>;
  updateMetadata(
    request: ContentUpdateMetadataMutationInput,
  ): Promise<ContentUpdateMetadataResponse>;
}
