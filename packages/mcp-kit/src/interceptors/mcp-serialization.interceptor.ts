import { Injectable, type NestInterceptor, type ExecutionContext, type CallHandler } from '@nestjs/common';
import { type Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { z } from 'zod';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import type { ImageContent, TextContent } from '@modelcontextprotocol/sdk/types.js';
import type { AudioContent } from '../serialization/mcp-content.js';
import { McpToolResult } from '../serialization/mcp-tool-result.js';

export interface ToolWireResult {
  content: Array<TextContent | ImageContent | AudioContent>;
  structuredContent?: Record<string, unknown>;
  isError?: boolean;
  _meta?: Record<string, unknown>;
}

function isPreFormatted(value: unknown): value is ToolWireResult {
  return (
    value !== null &&
    typeof value === 'object' &&
    'content' in value &&
    Array.isArray((value as { content: unknown }).content)
  );
}

@Injectable()
export class McpSerializationInterceptor implements NestInterceptor<unknown, ToolWireResult> {
  public constructor(private readonly outputSchema?: z.ZodObject<z.ZodRawShape>) {}

  public intercept(_context: ExecutionContext, next: CallHandler<unknown>): Observable<ToolWireResult> {
    return next.handle().pipe(
      map((value: unknown) => this.formatToolResult(value)),
    );
  }

  private formatToolResult(value: unknown): ToolWireResult {
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

    if (typeof value === 'object' && this.outputSchema) {
      const result = this.outputSchema.safeParse(value);
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
}
