import { gql } from 'graphql-request';
import type { FileAccessInput, UniqueFile } from './files.types';

export interface ContentUpdateMutationInput {
  contentId: string;
  ownerId: string;
  input: {
    url: string;
  };
}

export interface ContentUpdateMutationResult {
  contentUpdate: {
    id: string;
    ownerId: string;
    ownerType: string;
  };
}

export const CONTENT_UPDATE_MUTATION = gql`
  mutation ContentUpdate(
    $contentId: String!
    $ownerId: String
    $input: ContentUpdateInput!
  ) {
    contentUpdate(contentId: $contentId, ownerId: $ownerId, input: $input) {
      id
      ownerId
      ownerType
    }
  }
`;

export interface ContentDeleteMutationInput {
  contentDeleteId: string;
}

export interface ContentDeleteMutationResult {
  contentDelete: boolean;
}

export const CONTENT_DELETE_MUTATION = gql`
  mutation ContentDelete($contentDeleteId: String!) {
    contentDelete(id: $contentDeleteId)
  }
`;

export interface ContentDeleteByContentIdsMutationInput {
  contentIds: string[];
}

export interface ContentDeleteByContentIdsMutationResult {
  contentDeleteByContentIds: {
    id: string;
  }[];
}

export const CONTENT_DELETE_BY_IDS_MUTATION = gql`
  mutation ContentDeleteByContentIds($contentIds: [String!]!) {
    contentDeleteByContentIds(contentIds: $contentIds) {
      id
    }
  }
`;

export interface PaginatedContentQueryInput {
  skip: number;
  take: number;
  where: {
    key?: {
      startsWith?: string;
      in?: string[];
    };
  };
}

export interface PaginatedContentQueryResult {
  paginatedContent: {
    nodes: UniqueFile[];
    totalCount: number;
  };
}

export const PAGINATED_CONTENT_QUERY = gql`
  query PaginatedContent($skip: Int!, $take: Int!, $where: ContentWhereInput) {
    paginatedContent(skip: $skip, take: $take, where: $where) {
      nodes {
        id
        fileAccess
        key
        ownerType
        ownerId
        metadata
        byteSize
      }
      totalCount
    }
  }
`;

export interface PaginatedContentCountQueryInput {
  where: {
    key?: {
      startsWith?: string;
      in?: string[];
    };
  };
}

export interface PaginatedContentCountQueryResult {
  paginatedContent: {
    totalCount: number;
  };
}

// The GraphQL API doesn't have an optimization for count-only queries, so we pass 0 for both
// skip and take to avoid fetching any items while still getting the total count.
export const PAGINATED_CONTENT_COUNT_QUERY = gql`
  query PaginatedContentCount($where: ContentWhereInput) {
    paginatedContent(where: $where, skip: 0, take: 0) {
      totalCount
    }
  }
`;

export interface AddAccessesMutationInput {
  scopeId: string;
  fileAccesses: FileAccessInput[];
}

export interface AddAccessesMutationResult {
  createFileAccessesForContents: boolean;
}

export const ADD_ACCESSES_MUTATION = gql`
  mutation CreateFileAccessesForContents(
    $scopeId: String!
    $fileAccesses: [FileAccessContentChangeDto!]!
  ) {
    createFileAccessesForContents(
      scopeId: $scopeId
      fileAccesses: $fileAccesses
    )
  }
`;

export interface RemoveAccessesMutationInput {
  scopeId: string;
  fileAccesses: FileAccessInput[];
}

export interface RemoveAccessesMutationResult {
  removeFileAccessesForContents: boolean;
}

export const REMOVE_ACCESSES_MUTATION = gql`
  mutation RemoveFileAccessesForContents(
    $scopeId: String!
    $fileAccesses: [FileAccessContentChangeDto!]!
  ) {
    removeFileAccessesForContents(
      scopeId: $scopeId
      fileAccesses: $fileAccesses
    )
  }
`;

export const CONTENT_ID_BY_SCOPE_AND_METADATA_KET = gql`
    query PaginatedContent($skip: Int!, $take: Int!, $where: ContentWhereInput) {
      paginatedContent(skip: $skip, take: $take, where: $where) {
        nodes {
          id
        }
        totalCount
      }
    }
`;

export interface ContentByScopeAndMetadataKeyInput {
  skip: number;
  take: number;
  where: {
    ownerId: { equals: string };
    metadata: {
      path: string[];
      equals: string;
    };
  };
}

export interface ContentByScopeAndMetadataKeyResult {
  paginatedContent: {
    nodes: {
      id: string;
    }[];
    totalCount: number;
  };
}
