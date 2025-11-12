import { gql } from 'graphql-request';
import type { IngestionApiResponse } from './unique-file-ingestion.types';

export interface ContentUpsertMutationInput {
  input: {
    key: string;
    title: string;
    mimeType: string;
    ownerType: string;
    url?: string;
    byteSize?: number;
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

export interface ContentQueryInput {
  skip?: number;
  take?: number;
  orderBy?: Array<{
    key?: 'asc' | 'desc';
  }>;
  where?: {
    ownerId?: { equals: string };
    byteSize?: { gt: number };
    key?: { in: string[] };
  };
}

export const PAGINATED_CONTENT_QUERY = gql`
  query PaginatedContent(
    $skip: Int
    $take: Int
    $orderBy: [ContentOrderByWithRelationInput!]
    $where: ContentWhereInput
    $chatId: String
  ) {
    paginatedContent(
      skip: $skip
      take: $take
      orderBy: $orderBy
      where: $where
      chatId: $chatId
    ) {
      nodes {
        id
        key
      }
      totalCount
    }
  }
`;

export const CONTENT_DELETE_BY_KEY_MUTATION = gql`
  mutation ContentDeleteByKey(
    $key: String!
    $ownerType: String!
    $scopeId: String
    $url: String
    $baseUrl: String
  ) {
    contentDeleteByKey(
      key: $key
      ownerType: $ownerType
      scopeId: $scopeId
      url: $url
      baseUrl: $baseUrl
    )
  }
`;
