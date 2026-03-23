import { z } from 'zod';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import type { ImageContent, TextContent } from '@modelcontextprotocol/sdk/types.js';
import { McpToolResult } from './mcp-tool-result';
import type { AudioContent } from './mcp-content';

export interface ToolWireResult {
  content: Array<TextContent | ImageContent | AudioContent>;
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
  _meta?: Record<string, unknown>;
}

export function formatToolResult(
  value: unknown,
  outputSchema?: z.ZodObject<z.ZodRawShape>,
): ToolWireResult {
  if (value instanceof McpToolResult) {
    const result: ToolWireResult = {
      content: value.content,
      structuredContent: value.structuredContent,
      isError: value.isError,
    };
    if (value.meta) {
      result._meta = value.meta;
    }
    return result;
  }

  if (isPreFormatted(value)) {
    return value;
  }

  if (value === null || value === undefined) {
    return { content: [{ type: 'text', text: '' }] };
  }

  if (typeof value === 'string') {
    return { content: [{ type: 'text', text: value }] };
  }

  if (typeof value === 'number' || typeof value === 'boolean') {
    return { content: [{ type: 'text', text: String(value) }] };
  }

  if (typeof value === 'object' && outputSchema) {
    const result = outputSchema.safeParse(value);
    if (!result.success) {
      throw new McpError(
        ErrorCode.InternalError,
        `Tool output does not match declared output schema: ${result.error.message}`,
      );
    }
    return {
      content: [{ type: 'text', text: JSON.stringify(result.data, null, 2) }],
      structuredContent: result.data,
    };
  }

  return { content: [{ type: 'text', text: JSON.stringify(value, null, 2) }] };
}

function isPreFormatted(value: unknown): value is ToolWireResult {
  return (
    value !== null &&
    typeof value === 'object' &&
    'content' in value &&
    Array.isArray((value as { content: unknown }).content)
  );
}
