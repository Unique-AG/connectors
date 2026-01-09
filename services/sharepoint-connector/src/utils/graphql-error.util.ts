import { isObjectType } from 'remeda';

export function getErrorCodeFromGraphqlRequest(error: unknown): number {
  if (!isObjectType(error)) {
    return 0;
  }

  const graphQlError = error as {
    response?: {
      errors?: Array<{
        extensions?: {
          response?: {
            statusCode?: number;
          };
        };
      }>;
    };
  };

  return graphQlError?.response?.errors?.[0]?.extensions?.response?.statusCode ?? 0;
}
