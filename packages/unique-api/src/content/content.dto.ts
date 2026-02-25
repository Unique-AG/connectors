import { z } from 'zod/v4';
import { UniqueOwnerTypeOptions } from '../types/unique-entity.types';

// Enums

export const OwnerTypeSchema = z.enum(UniqueOwnerTypeOptions);

export const IngestionStateSchema = z.enum([
  'FAILED',
  'FAILED_MALWARE_FOUND',
  'FAILED_MALWARE_SCAN_TIMEOUT',
  'FAILED_METADATA_VALIDATION',
  'FAILED_TOO_LESS_CONTENT',
  'FAILED_REDELIVERED',
  'FAILED_PARSING',
  'FAILED_IMAGE',
  'FAILED_CREATING_CHUNKS',
  'FAILED_EMBEDDING',
  'FAILED_GETTING_FILE',
  'FAILED_TIMEOUT',
  'FAILED_TABLE_LIMIT_EXCEEDED',
  'MALWARE_SCANNING',
  'METADATA_VALIDATION',
  'QUEUED',
  'INGESTION_READING',
  'INGESTION_CHUNKING',
  'INGESTION_EMBEDDING',
  'FINISHED',
  'RECREATING_VECETORDB_INDEX',
  'RE_EMBEDDING',
  'RE_INGESTING',
  'REBUILDING_METADATA',
  'CHECKING_INTEGRITY',
  'RETRYING',
]);

// Nested models

export const ChunkSchema = z.object({
  id: z.string(),
  startPage: z.number().nullable(),
  endPage: z.number().nullable(),
  order: z.number().nullable(),
  embedding: z.unknown().nullable(),
  embeddingsFirst10: z.unknown().nullable(),
  model: z.string().nullable(),
  vectorId: z.string(),
  contentId: z.string(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  text: z.string(),
  createdBy: z.string().nullable(),
  companyId: z.string().nullable(),
});

// Main Content schema

export const ContentSchema = z.object({
  id: z.string(),
  key: z.string(),
  title: z.string().nullable(),
  description: z.string().nullable(),
  mimeType: z.string(),
  byteSize: z.number(),
  url: z.string().nullable(),
  readUrl: z.string().nullable(),
  writeUrl: z.string().nullable(),
  pdfPreviewWriteUrl: z.string().nullable(),
  metadata: z.unknown().nullable(),
  ownerId: z.string(),
  ownerType: OwnerTypeSchema,
  expiresAt: z.iso.datetime().nullable(),
  expiresInDays: z.number().nullable(),
  internallyStoredAt: z.iso.datetime().nullable(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  ingestionProgress: z.number(),
  ingestionState: IngestionStateSchema,
  ingestionStateUpdatedAt: z.iso.datetime().nullable(),
  ingestionStateDetails: z.string().nullable(),
  externalFileOwner: z.string().nullable(),
  ingestionConfig: z.unknown().nullable(),
  appliedIngestionConfig: z.unknown().nullable(),
  previewPdfFileName: z.string().nullable(),
  expiredAt: z.iso.datetime().nullable(),
  deletedAt: z.iso.datetime().nullable(),
  fileAccess: z.array(z.string()),
  fileAccessState: z.unknown().nullable(),
  createdBy: z.string().nullable(),
  companyId: z.string().nullable(),
  chunks: z.array(ChunkSchema).optional(),
});

export type Content = z.infer<typeof ContentSchema>;
