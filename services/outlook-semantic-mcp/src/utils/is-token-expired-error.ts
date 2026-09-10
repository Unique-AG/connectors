import { isUpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { GraphError } from '@microsoft/microsoft-graph-client';

/** Callers branch on "this token cannot be used", so a permanently revoked grant counts too. */
export const isTokenExpiredError = (error: unknown) =>
  isUpstreamCredentialRevokedError(error) ||
  (error instanceof GraphError && error.statusCode === 401);
