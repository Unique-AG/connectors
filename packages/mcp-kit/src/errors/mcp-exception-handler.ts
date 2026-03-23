import { McpError } from '@modelcontextprotocol/sdk/types.js';
import { DefectError } from './defect.js';
import { McpBaseError } from './base.js';
import { UpstreamConnectionRequiredError } from './failures.js';

export interface McpToolErrorResponse {
  isError: true;
  content: Array<{ type: 'text'; text: string }>;
}

export function handleMcpToolError(error: unknown): McpToolErrorResponse {
  if (error instanceof McpError) {
    throw error;
  }

  if (error instanceof UpstreamConnectionRequiredError) {
    throw error;
  }

  if (error instanceof McpBaseError) {
    console.warn(`[MCP] Tool failure [${error.errorCode}]: ${error.message}`, error.metadata.context);
    return {
      isError: true,
      content: [{ type: 'text', text: error.message }],
    };
  }

  if (error instanceof DefectError) {
    console.error('[MCP] Defect encountered:', error.stack);
    return {
      isError: true,
      content: [{ type: 'text', text: 'Internal server error. This is a bug.' }],
    };
  }

  console.error('[MCP] Unexpected error:', error instanceof Error ? error.stack : error);
  return {
    isError: true,
    content: [{ type: 'text', text: 'An unexpected error occurred.' }],
  };
}
