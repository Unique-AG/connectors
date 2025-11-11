import { gql } from 'graphql-request';
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
        ${scopeAccessFields}
      }
    }
  `;
}
