import { Injectable, type NestInterceptor, type ExecutionContext, type CallHandler } from '@nestjs/common';
import { type Observable } from 'rxjs';
import { map } from 'rxjs/operators';
import { isBoolean, isNullish, isNumber, isObjectType, isString } from 'remeda';
import { z } from 'zod';
import { ErrorCode, McpError } from '@modelcontextprotocol/sdk/types.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';
import { McpToolResult } from '../serialization/mcp-tool-result.js';

/**
 * Returns `true` when `value` is already in `CallToolResult` shape (has a `content` array),
 * allowing pre-formatted responses to pass through without re-serialization.
 */
function isPreFormatted(value: unknown): value is CallToolResult {
  return (
    isObjectType(value) &&
    'content' in value &&
    Array.isArray((value as { content: unknown }).content)
  );
}

/**
 * NestJS interceptor that converts tool handler return values into the `CallToolResult`
 * shape expected by the MCP protocol layer.
 *
 * Handles `McpToolResult` instances, pre-formatted wire results, primitives (string,
 * number, boolean, null), and plain objects. Plain objects are JSON-serialized into a
 * text content item; when `outputSchema` is provided they are also validated and included
 * as `structuredContent`.
 */
@Injectable()
export class McpSerializationInterceptor implements NestInterceptor<unknown, CallToolResult> {
  /**
   * @param outputSchema When provided, plain-object return values are validated against
   *   this schema and, on success, included as `structuredContent` in the wire response.
   *   Validation failure throws an `McpError` with `InternalError` code.
   */
  public constructor(private readonly outputSchema?: z.ZodObject<z.ZodRawShape>) {}

  public intercept(_context: ExecutionContext, next: CallHandler<unknown>): Observable<CallToolResult> {
    return next.handle().pipe(
      map((value: unknown) => this.formatToolResult(value)),
    );
  }

  private formatToolResult(value: unknown): CallToolResult {
    if (value instanceof McpToolResult) {
      const result: CallToolResult = {
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

    if (isNullish(value)) {
      return { content: [{ type: 'text', text: '' }] };
    }

    if (isString(value)) {
      return { content: [{ type: 'text', text: value }] };
    }

    if (isNumber(value) || isBoolean(value)) {
      return { content: [{ type: 'text', text: String(value) }] };
    }

    if (isObjectType(value) && this.outputSchema) {
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
