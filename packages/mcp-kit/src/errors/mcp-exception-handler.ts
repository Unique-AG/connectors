import { McpError } from '@modelcontextprotocol/sdk/types.js';
import { isError } from 'remeda';
import { DefectError } from './defect.js';
import { McpBaseError } from './base.js';
import { UpstreamConnectionRequiredError } from './failures.js';

export interface McpLogger {
  warn(message: string, context?: unknown): void;
  error(message: string, context?: unknown): void;
}

export interface McpToolErrorResponse {
  isError: true;
  content: Array<{ type: 'text'; text: string }>;
}

export function handleMcpToolError(error: unknown, logger: McpLogger): McpToolErrorResponse {
  if (error instanceof McpError) {
    throw error;
  }

  if (error instanceof UpstreamConnectionRequiredError) {
    throw error;
  }

  if (error instanceof McpBaseError) {
    logger.warn(`[MCP] Tool failure [${error.errorCode}]: ${error.message}`, error.metadata.context);
    return {
      isError: true,
      content: [{ type: 'text', text: error.message }],
    };
  }

  if (error instanceof DefectError) {
    const stack = error.stack !== undefined ? error.stack : error.message;
    logger.error('[MCP] Defect encountered:', stack);
    return {
      isError: true,
      content: [{ type: 'text', text: 'Internal server error. This is a bug.' }],
    };
  }

  const detail = isError(error) ? (error.stack !== undefined ? error.stack : error.message) : String(error);
  logger.error('[MCP] Unexpected error:', detail);
  return {
    isError: true,
    content: [{ type: 'text', text: 'An unexpected error occurred.' }],
  };
}
