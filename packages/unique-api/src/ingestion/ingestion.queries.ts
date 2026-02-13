import { gql } from 'graphql-request';

import type { FileAccessKey } from '../files/files.types';
import type { IngestionApiResponse } from './ingestion.types';

export interface IngestionConfig {
  uniqueIngestionMode?:
    | 'SKIP_INGESTION'
    | 'INGESTION'
    | 'SKIP_EXCEL_INGESTION'
    | 'EXTERNAL_INGESTION';
}

export interface ContentUpsertMutationInput {
  input: {
    key: string;
    title: string;
    mimeType: string;
    ownerType: string;
    url?: string;
    byteSize?: number;
    fileAccess?: FileAccessKey[];
    ingestionConfig?: IngestionConfig;
    metadata?: Record<string, unknown>;
  };
  fileUrl?: string;
  chatId?: string;
  scopeId: string;
  sourceOwnerType: string;
  sourceName: string;
  sourceKind: string;
  storeInternally: boolean;
  baseUrl?: string;
}

export interface ContentUpsertMutationResult {
  contentUpsert: IngestionApiResponse;
}

export const CONTENT_UPSERT_MUTATION = gql`
  mutation ContentUpsert(
    $input: ContentCreateInput!
    $fileUrl: String
    $chatId: String
    $scopeId: String
    $sourceOwnerType: String
    $sourceName: String
    $sourceKind: String
    $storeInternally: Boolean
    $baseUrl: String
  ) {
    contentUpsert(
      input: $input
      fileUrl: $fileUrl
      chatId: $chatId
      scopeId: $scopeId
      sourceOwnerType: $sourceOwnerType
      sourceName: $sourceName
      sourceKind: $sourceKind
      storeInternally: $storeInternally
      baseUrl: $baseUrl
    ) {
      id
      key
      title
      byteSize
      mimeType
      ownerType
      ownerId
      writeUrl
      readUrl
      createdAt
      internallyStoredAt
      source {
        kind
        name
      }
    }
  }
`;
