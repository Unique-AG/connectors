import { gql } from "graphql-request";
import { UniqueAccessType, UniqueEntityType } from "../types";
import type { Scope } from "./unique-scopes.types";

export interface GenerateScopesBasedOnPathsMutationInput {
  paths: string[];
  inheritAccess?: boolean;
}

export interface GenerateScopesBasedOnPathsMutationResult {
  generateScopesBasedOnPaths: Scope[];
}

export function getGenerateScopesBasedOnPathsMutation(
  includePermissions: boolean,
): string {
  const scopeAccessFields = includePermissions
    ? `scopeAccess {
          entityId
          type
          entityType
        }`
    : "";

  return gql`
    mutation GenerateScopesBasedOnPaths($paths: [String!]!, $inheritAccess: Boolean) {
      generateScopesBasedOnPaths(paths: $paths, inheritAccess: $inheritAccess) {
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
    externalId?: {
      equals?: string;
      startsWith?: string;
    };
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
    externalId?: string;
    // There's a typo in Unique API: "parrent" instead of "parent"
    parrentScope?: {
      connect: {
        id: string;
      };
    };
  };
}

export interface UpdateScopeMutationResult {
  updateScope: {
    id: string;
    name: string;
    externalId: string | null;
    parentId: string | null;
  };
}

export const UPDATE_SCOPE_MUTATION = gql`
  mutation UpdateScope($id: String!, $input: ScopeUpdateInput!) {
    updateScope(id: $id, input: $input) {
      id
      name
      externalId
      parentId
    }
  }
`;

export interface DeleteFolderMutationInput {
  scopeId: string;
  recursive: boolean;
}

export interface DeleteFolderMutationResult {
  deleteFolder: {
    successFolders: Array<{
      id: string;
      name: string;
      path: string;
    }>;
    failedFolders: Array<{
      id: string;
      name: string;
      failReason: string;
      path: string;
    }>;
  };
}

export const DELETE_FOLDER_MUTATION = gql`
  mutation DeleteFolder($scopeId: String!, $recursive: Boolean!) {
    deleteFolder(scopeId: $scopeId, recursive: $recursive) {
      failedFolders {
        id
        name
        failReason
        path
      }
      successFolders {
        id
        name
        path
      }
    }
  }
`;
