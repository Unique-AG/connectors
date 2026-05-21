import { GraphError } from '@microsoft/microsoft-graph-client';

export const isTokenExpiredError = (error: unknown) =>
  error instanceof GraphError && error.statusCode === 401;
