import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';

/**
 * Thrown when an upstream credential (e.g. a Microsoft refresh token) is permanently invalid.
 * Extends `McpError` so the module emits a JSON-RPC error rather than an `isError` tool result,
 * which is the only path a client turns into a re-auth prompt. Callers revoke the user's MCP
 * tokens first, so the next `/mcp` request is 401 even if the client ignores this error.
 */
export class UpstreamCredentialRevokedError extends McpError {
  public constructor(cause?: string) {
    // Clients match both phrases to tell an expired session from a permission error.
    const message = cause
      ? `Re-authentication required (invalid token): ${cause}`
      : 'Re-authentication required (invalid token). Please reconnect this MCP server.';
    super(ErrorCode.InternalError, message);
    this.name = 'UpstreamCredentialRevokedError';
  }
}

/** Name-based: `instanceof` fails across two copies of the SDK and on a deserialized error. */
export function isUpstreamCredentialRevokedError(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    'name' in error &&
    error.name === 'UpstreamCredentialRevokedError'
  );
}

const PERMANENT_UPSTREAM_OAUTH_ERRORS = new Set([
  'invalid_grant',
  'interaction_required',
  'consent_required',
]);

export function isPermanentUpstreamOAuthError(errorCode: string | undefined): boolean {
  return errorCode !== undefined && PERMANENT_UPSTREAM_OAUTH_ERRORS.has(errorCode);
}
