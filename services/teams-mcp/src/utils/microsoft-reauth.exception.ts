import { McpError } from '@modelcontextprotocol/sdk/types.js';
import { ErrorCode } from '@modelcontextprotocol/sdk/types.js';

/**
 * Thrown when the Microsoft Graph refresh token is permanently invalid —
 * e.g. `invalid_grant`, device removed from tenant, Conditional Access policy changed.
 *
 * Extends McpError so the tool handler re-throws it as a JSON-RPC error response
 * (code -32603) instead of wrapping it in `{ isError: true }`. The client SDK
 * converts the JSON-RPC error into a thrown McpError, giving the client a clear
 * signal that the user must re-authenticate rather than just a failed tool call.
 */
export class MicrosoftReauthRequiredException extends McpError {
  constructor(cause?: string) {
    const message = cause
      ? `Microsoft re-authentication required: ${cause}`
      : 'Microsoft re-authentication required. Please reconnect your Microsoft account.';
    super(ErrorCode.InternalError, message);
    this.name = 'MicrosoftReauthRequiredException';
  }
}
