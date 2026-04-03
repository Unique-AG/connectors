import { ErrorCode } from '@modelcontextprotocol/sdk/types.js';
import { type McpErrorMetadata, McpBaseError } from './base.js';

/** Throw when the caller cannot be identified — missing or invalid credentials. */
export class McpAuthenticationError extends McpBaseError {
  public readonly errorCode = 'MCP_AUTHENTICATION_FAILED';

  constructor(message: string, context?: Record<string, unknown>, options?: ErrorOptions) {
    super(message, { mcpErrorCode: ErrorCode.InvalidRequest, retryable: false, context }, options);
  }
}

/** Throw when the caller is authenticated but lacks permission to perform the action. */
export class McpAuthorizationError extends McpBaseError {
  public readonly errorCode = 'MCP_AUTHORIZATION_FAILED';

  constructor(message: string, context?: Record<string, unknown>, options?: ErrorOptions) {
    super(message, { mcpErrorCode: ErrorCode.InvalidRequest, retryable: false, context }, options);
  }
}

/** Throw when tool or resource input parameters fail validation. */
export class McpValidationError extends McpBaseError {
  public readonly errorCode = 'MCP_VALIDATION_FAILED';

  constructor(message: string, context?: Record<string, unknown>, options?: ErrorOptions) {
    super(message, { mcpErrorCode: ErrorCode.InvalidParams, retryable: false, context }, options);
  }
}

/** Throw for a generic, tool-specific failure not covered by a more specific error type. */
export class McpToolError extends McpBaseError {
  public readonly errorCode = 'MCP_TOOL_ERROR';

  constructor(message: string, metadata?: McpErrorMetadata, options?: ErrorOptions) {
    super(message, { retryable: false, ...metadata }, options);
  }
}

/** Throw when the MCP protocol contract is violated (e.g. unexpected message shape or sequence). */
export class McpProtocolError extends McpBaseError {
  public readonly errorCode = 'MCP_PROTOCOL_ERROR';

  constructor(message: string, mcpErrorCode?: number, options?: ErrorOptions) {
    super(message, { mcpErrorCode, retryable: false }, options);
  }
}

/**
 * Throw when a tool requires an upstream connection that has never been established.
 * The `reconnectUrl` should be presented to the user to initiate the OAuth/auth flow.
 */
export class UpstreamConnectionRequiredError extends McpBaseError {
  public readonly errorCode = 'MCP_UPSTREAM_CONNECTION_REQUIRED';

  constructor(
    /** Human-readable name of the upstream service (e.g. `"GitHub"`). */
    public readonly upstreamName: string,
    /** URL the user must visit to authorise and establish the connection. */
    public readonly reconnectUrl: string,
    options?: ErrorOptions,
  ) {
    super(`Upstream connection required: ${upstreamName}`, { retryable: true }, options);
  }
}

/**
 * Throw when a previously established upstream connection has been dropped mid-session.
 * Marked retryable — the caller may attempt reconnection.
 */
export class UpstreamConnectionLostError extends McpBaseError {
  public readonly errorCode = 'MCP_UPSTREAM_CONNECTION_LOST';

  constructor(
    /** Human-readable name of the upstream service that disconnected. */
    public readonly upstreamName: string,
    message?: string,
    options?: ErrorOptions,
  ) {
    super(message ?? `Upstream connection lost: ${upstreamName}`, { retryable: true }, options);
  }
}
