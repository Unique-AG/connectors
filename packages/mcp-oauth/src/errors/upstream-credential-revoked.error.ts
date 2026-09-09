import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';

/**
 * Thrown when an upstream credential (e.g. a Microsoft refresh token) is permanently invalid.
 *
 * Extends `McpError` so the MCP module re-throws it as a JSON-RPC error rather than folding it
 * into an `isError: true` tool result. A tool result reaches the client as a successful call and
 * only its text survives, so the client has nothing to act on; a JSON-RPC error reaches the
 * client's error path, which is where re-authentication is triggered.
 *
 * The message deliberately spells out both `re-authentication required` and `invalid token`:
 * clients match those phrases to tell an expired session apart from an application-level
 * permission error, and they check thrown errors and tool-result text against separate phrase
 * lists. Carrying both keeps the signal intact on either path.
 *
 * Callers revoke the user's MCP tokens before throwing, so the next `/mcp` request is answered
 * with 401 even if a client ignores this error entirely.
 */
export class UpstreamCredentialRevokedError extends McpError {
  public constructor(cause?: string) {
    const message = cause
      ? `Re-authentication required (invalid token): ${cause}`
      : 'Re-authentication required (invalid token). Please reconnect this MCP server.';
    super(ErrorCode.InternalError, message);
    this.name = 'UpstreamCredentialRevokedError';
  }
}

/**
 * Matches on the name rather than with `instanceof`, and accepts any object rather than only a
 * real `Error`: the class is loaded once per copy of the MCP SDK in the dependency graph, and an
 * error that crossed a serialization boundary (e.g. a queued background job) arrives with its
 * prototype gone. `instanceof` silently returns false in both cases.
 */
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
