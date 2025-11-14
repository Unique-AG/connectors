import { gql } from 'graphql-request';
import type { Scope, ScopeAccess } from './unique-scopes.types';

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
        ${scopeAccessFields}
      }
    }
  `;
}

export interface CreateScopeAccessesMutationInput {
  scopeId: string;
  scopeAccesses: ScopeAccess[];
  applyToSubScopes?: boolean;
}

export interface CreateScopeAccessesMutationResult {
  createScopeAccesses: boolean;
}

export const CREATE_SCOPE_ACCESSES_MUTATION = gql`
  mutation CreateScopeAccesses($scopeAccesses: [ScopeAccess!]!, $scopeId: String!, $applyToSubScopes: Boolean) {
    createScopeAccesses(scopeAccesses: $scopeAccesses, scopeId: $scopeId, applyToSubScopes: $applyToSubScopes)
  }
`;

export interface DeleteScopeAccessesMutationInput {
  scopeId: string;
  scopeAccesses: ScopeAccess[];
  applyToSubScopes?: boolean;
}

export interface DeleteScopeAccessesMutationResult {
  deleteScopeAccesses: boolean;
}

export const DELETE_SCOPE_ACCESSES_MUTATION = gql`
  mutation DeleteScopeAccesses($scopeAccesses: [ScopeAccess!]!, $scopeId: String!, $applyToSubScopes: Boolean) {
    deleteScopeAccesses(scopeAccesses: $scopeAccesses, scopeId: $scopeId, applyToSubScopes: $applyToSubScopes)
  }
`;
