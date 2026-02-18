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
  source: { kind: string; name: string };
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

export enum IngestionState {
  CheckingIntegrity = 'CHECKING_INTEGRITY',
  Failed = 'FAILED',
  FailedCreatingChunks = 'FAILED_CREATING_CHUNKS',
  FailedEmbedding = 'FAILED_EMBEDDING',
  FailedGettingFile = 'FAILED_GETTING_FILE',
  FailedImage = 'FAILED_IMAGE',
  FailedMalwareFound = 'FAILED_MALWARE_FOUND',
  FailedMetadataValidation = 'FAILED_METADATA_VALIDATION',
  FailedMalwareScanTimeout = 'FAILED_MALWARE_SCAN_TIMEOUT',
  FailedParsing = 'FAILED_PARSING',
  FailedRedelivered = 'FAILED_REDELIVERED',
  FailedTimeout = 'FAILED_TIMEOUT',
  FailedTooLessContent = 'FAILED_TOO_LESS_CONTENT',
  FailedTableLimitExceeded = 'FAILED_TABLE_LIMIT_EXCEEDED',
  Finished = 'FINISHED',
  IngestionChunking = 'INGESTION_CHUNKING',
  IngestionEmbedding = 'INGESTION_EMBEDDING',
  IngestionReading = 'INGESTION_READING',
  MalwareScanning = 'MALWARE_SCANNING',
  MetadataValidation = 'METADATA_VALIDATION',
  Queued = 'QUEUED',
  RebuildingMetadata = 'REBUILDING_METADATA',
  RecreatingVecetordbIndex = 'RECREATING_VECETORDB_INDEX',
  Retrying = 'RETRYING',
  ReEmbedding = 'RE_EMBEDDING',
  ReIngesting = 'RE_INGESTING',
}
