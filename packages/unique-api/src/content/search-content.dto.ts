import { z } from 'zod';
import { IngestionState } from '../ingestion/ingestion.types';
import { UniqueOwnerTypeOptions } from '../types/unique-entity.types';

export enum UniqueQLOperator {
  EQUALS = 'equals',
  NOT_EQUALS = 'notEquals',
  GREATER_THAN = 'greaterThan',
  GREATER_THAN_OR_EQUAL = 'greaterThanOrEqual',
  LESS_THAN = 'lessThan',
  LESS_THAN_OR_EQUAL = 'lessThanOrEqual',
  IN = 'in',
  NOT_IN = 'notIn',
  CONTAINS = 'contains',
  NOT_CONTAINS = 'notContains',
  IS_NULL = 'isNull',
  IS_NOT_NULL = 'isNotNull',
  IS_EMPTY = 'isEmpty',
  IS_NOT_EMPTY = 'isNotEmpty',
  NESTED = 'nested',
}

export const UniqueQLConditionSchema = z.object({
  path: z.array(z.string()),
  operator: z.enum(UniqueQLOperator),
  value: z.union([z.string(), z.number(), z.boolean(), z.array(z.string())]),
});
export type UniqueQLCondition = z.infer<typeof UniqueQLConditionSchema>;

type MetadataFilterInput =
  | UniqueQLCondition
  | { and: MetadataFilterInput[] }
  | { or: MetadataFilterInput[] };

export const MetadataFilterSchema: z.ZodType<MetadataFilterInput> = z.union([
  UniqueQLConditionSchema,
  z.object({ and: z.lazy(() => z.array(MetadataFilterSchema)) }),
  z.object({ or: z.lazy(() => z.array(MetadataFilterSchema)) }),
]);
export type MetadataFilter = z.infer<typeof MetadataFilterSchema>;

export enum SearchType {
  VECTOR = 'VECTOR',
  COMBINED = 'COMBINED',
  FULL_TEXT = 'FULL_TEXT',
  POSTGRES_FULL_TEXT = 'POSTGRES_FULL_TEXT',
}

export const PublicSearchRequestSchema = z.object({
  prompt: z.string(),
  searchType: z.enum(SearchType),
  chatId: z.string().optional(),
  scopeIds: z.array(z.string()).optional(),
  contentIds: z.array(z.string()).optional(),
  chatOnly: z.boolean().optional(),
  limit: z.number().int().min(1).max(1000).optional(),
  page: z.number().int().min(0).optional(),
  scoreThreshold: z.number().min(0).max(1).optional(),
  language: z.string().optional(),
  metaDataFilter: MetadataFilterSchema.optional(),
});
export type PublicSearchRequest = z.infer<typeof PublicSearchRequestSchema>;

export const SearchResultItemSchema = z.object({
  id: z.string(),
  key: z.string(),
  title: z.string().nullable(),
  description: z.string().nullable(),
  mimeType: z.string(),
  byteSize: z.number(),
  url: z.string().nullable(),
  metadata: z.unknown().nullable(),
  version: z.number(),
  collectionName: z.string(),
  sourceId: z.string(),
  ownerId: z.string(),
  ownerType: z.enum(UniqueOwnerTypeOptions),
  expiresAt: z.iso.datetime().nullable(),
  internallyStoredAt: z.iso.datetime().nullable(),
  createdAt: z.iso.datetime(),
  updatedAt: z.iso.datetime(),
  ingestionProgress: z.number(),
  ingestionState: z.nativeEnum(IngestionState),
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
  text: z.string(),
  order: z.number(),
  chunkId: z.string(),
  startPage: z.number(),
  endPage: z.number(),
});
export type SearchResultItem = z.infer<typeof SearchResultItemSchema>;

export const SearchResultSchema = z.array(SearchResultItemSchema);
export type SearchResult = z.infer<typeof SearchResultSchema>;
