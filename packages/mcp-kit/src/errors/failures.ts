import { ErrorCode } from '@modelcontextprotocol/sdk/types.js';
import { type McpErrorMetadata, McpBaseError } from './base.js';

export class McpAuthenticationError extends McpBaseError {
  public readonly errorCode = 'MCP_AUTHENTICATION_FAILED';

  constructor(message: string, context?: Record<string, unknown>, options?: ErrorOptions) {
    super(message, { mcpErrorCode: ErrorCode.InvalidRequest, retryable: false, context }, options);
  }
}

export class McpAuthorizationError extends McpBaseError {
  public readonly errorCode = 'MCP_AUTHORIZATION_FAILED';

  constructor(message: string, context?: Record<string, unknown>, options?: ErrorOptions) {
    super(message, { mcpErrorCode: ErrorCode.InvalidRequest, retryable: false, context }, options);
  }
}

export class McpValidationError extends McpBaseError {
  public readonly errorCode = 'MCP_VALIDATION_FAILED';

  constructor(message: string, context?: Record<string, unknown>, options?: ErrorOptions) {
    super(message, { mcpErrorCode: ErrorCode.InvalidParams, retryable: false, context }, options);
  }
}

export class McpToolError extends McpBaseError {
  public readonly errorCode = 'MCP_TOOL_ERROR';

  constructor(message: string, metadata?: McpErrorMetadata, options?: ErrorOptions) {
    super(message, { retryable: false, ...metadata }, options);
  }
}

export class McpProtocolError extends McpBaseError {
  public readonly errorCode = 'MCP_PROTOCOL_ERROR';

  constructor(message: string, mcpErrorCode?: number, options?: ErrorOptions) {
    super(message, { mcpErrorCode, retryable: false }, options);
  }
}

export class UpstreamConnectionRequiredError extends McpBaseError {
  public readonly errorCode = 'MCP_UPSTREAM_CONNECTION_REQUIRED';

  constructor(
    public readonly upstreamName: string,
    public readonly reconnectUrl: string,
    options?: ErrorOptions,
  ) {
    super(`Upstream connection required: ${upstreamName}`, { retryable: true }, options);
  }
}

export class UpstreamConnectionLostError extends McpBaseError {
  public readonly errorCode = 'MCP_UPSTREAM_CONNECTION_LOST';

  constructor(
    public readonly upstreamName: string,
    message?: string,
    options?: ErrorOptions,
  ) {
    super(message !== undefined ? message : `Upstream connection lost: ${upstreamName}`, { retryable: true }, options);
  }
}
