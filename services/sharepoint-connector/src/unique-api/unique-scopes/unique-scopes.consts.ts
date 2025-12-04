import { gql } from 'graphql-request';
import { UniqueAccessType, UniqueEntityType } from '../types';
import type { Scope } from './unique-scopes.types';

export interface GenerateScopesBasedOnPathsMutationInput {
  paths: string[];
}

export type GenerateScopesBasedOnPathsMutationResult = {
  generateScopesBasedOnPaths: Scope[];
};

export function getGenerateScopesBasedOnPathsMutation(includePermissions: boolean): string {
  const scopeAccessFields = includePermissions
    ? `scopeAccess {
          entityId
          type
          entityType
        }`
    : '';

  return gql`
    mutation GenerateScopesBasedOnPaths($paths: [String!]!) {
      generateScopesBasedOnPaths(paths: $paths) {
        id
        name
        parentId
        externalId
        ${scopeAccessFields}
      }
    }
  `;
}

export interface ScopeAccessChangeDto {
  accessType: UniqueAccessType;
  entityId: string;
  entityType: UniqueEntityType;
}

export interface CreateScopeAccessesMutationInput {
  scopeId: string;
  scopeAccesses: ScopeAccessChangeDto[];
  applyToSubScopes?: boolean;
  skipFileAccessPropagation?: boolean;
}

export interface CreateScopeAccessesMutationResult {
  createScopeAccesses: boolean;
}

export const CREATE_SCOPE_ACCESSES_MUTATION = gql`
  mutation CreateScopeAccesses(
    $scopeAccesses: [ScopeAccessChangeDto!]!
    $scopeId: String!
    $applyToSubScopes: Boolean
    $skipFileAccessPropagation: Boolean
  ) {
    createScopeAccesses(
      scopeAccesses: $scopeAccesses
      scopeId: $scopeId
      applyToSubScopes: $applyToSubScopes
      skipFileAccessPropagation: $skipFileAccessPropagation
    )
  }
`;

export interface DeleteScopeAccessesMutationInput {
  scopeId: string;
  scopeAccesses: ScopeAccessChangeDto[];
  applyToSubScopes?: boolean;
  skipFileAccessPropagation?: boolean;
}

export interface DeleteScopeAccessesMutationResult {
  deleteScopeAccesses: boolean;
}

export const DELETE_SCOPE_ACCESSES_MUTATION = gql`
  mutation DeleteScopeAccesses(
    $scopeAccesses: [ScopeAccessChangeDto!]!
    $scopeId: String!
    $applyToSubScopes: Boolean
    $skipFileAccessPropagation: Boolean
  ) {
    deleteScopeAccesses(
      scopeAccesses: $scopeAccesses
      scopeId: $scopeId
      applyToSubScopes: $applyToSubScopes
      skipFileAccessPropagation: $skipFileAccessPropagation
    )
  }
`;

export interface PaginatedScopeQueryInput {
  skip: number;
  take: number;
  where: {
    id?: {
      equals: string;
    };
    name?: {
      equals: string;
    };
    parentId?: {
      equals: string;
    } | null;
  };
}

export interface PaginatedScopeQueryResult {
  paginatedScope: {
    totalCount: number;
    nodes: Scope[];
  };
}

export const PAGINATED_SCOPE_QUERY = gql`
  query PaginatedScope($skip: Int!, $take: Int!, $where: ScopeWhereInput!) {
    paginatedScope(skip: $skip, take: $take, where: $where) {
      totalCount
      nodes {
        id
        name
        parentId
        externalId
      }
    }
  }
`;

export interface UpdateScopeMutationInput {
  id: string;
  input: {
    externalId: string;
  };
}

export interface UpdateScopeMutationResult {
  updateScope: {
    id: string;
    name: string;
    externalId: string | null;
  };
}

export const UPDATE_SCOPE_MUTATION = gql`
  mutation UpdateScope($id: String!, $input: ScopeUpdateInput!) {
    updateScope(id: $id, input: $input) {
      id
      name
      externalId
    }
  }
`;
