import { gql } from 'graphql-request';
import type { UniqueFile, UniqueFileAccessInput } from './unique-files.types';

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
  mutation ContentUpdate($contentId: String!, $ownerId: String, $input: ContentUpdateInput!) {
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
      }
      totalCount
    }
  }
`;

export interface AddAccessesMutationInput {
  scopeId: string;
  fileAccesses: UniqueFileAccessInput[];
}

export interface AddAccessesMutationResult {
  createFileAccessesForContents: boolean;
}

export const ADD_ACCESSES_MUTATION = gql`
  mutation CreateFileAccessesForContents($scopeId: String!, $fileAccesses: [FileAccessContentChangeDto!]!) {
    createFileAccessesForContents(scopeId: $scopeId, fileAccesses: $fileAccesses)
  }
`;

export interface RemoveAccessesMutationInput {
  scopeId: string;
  fileAccesses: UniqueFileAccessInput[];
}

export interface RemoveAccessesMutationResult {
  removeFileAccessesForContents: boolean;
}

export const REMOVE_ACCESSES_MUTATION = gql`
  mutation RemoveFileAccessesForContents($scopeId: String!, $fileAccesses: [FileAccessContentChangeDto!]!) {
    removeFileAccessesForContents(scopeId: $scopeId, fileAccesses: $fileAccesses)
  }
`;
