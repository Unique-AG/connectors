import { type ArgumentsHost, Catch, Injectable, Logger, type ExceptionFilter } from '@nestjs/common';
import { McpError } from '@modelcontextprotocol/sdk/types.js';
import { isError } from 'remeda';
import { DefectError } from '../errors/defect.js';
import { McpBaseError } from '../errors/base.js';
import { UpstreamConnectionRequiredError } from '../errors/failures.js';
import type { CallToolResult } from '@modelcontextprotocol/sdk/types.js';

/**
 * Catches all errors thrown during MCP tool execution and converts them to the MCP wire format
 * (`CallToolResult`). `McpError` and `UpstreamConnectionRequiredError` are re-thrown so they can
 * propagate to the transport layer unchanged; all other errors are serialised into an error
 * content block.
 */
@Catch()
@Injectable()
export class McpExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(McpExceptionFilter.name);

  /** @param _host Intentionally unused — MCP execution has no HTTP context. */
  public catch(exception: unknown, _host: ArgumentsHost): CallToolResult {
    if (exception instanceof McpError) {
      throw exception;
    }

    if (exception instanceof UpstreamConnectionRequiredError) {
      throw exception;
    }

    if (exception instanceof McpBaseError) {
      this.logger.warn(`[MCP] Tool failure [${exception.errorCode}]: ${exception.message}`, exception.metadata.context);
      return { isError: true, content: [{ type: 'text', text: exception.message }] };
    }

    if (exception instanceof DefectError) {
      this.logger.error('[MCP] Defect encountered:', exception.stack ?? exception.message);
      return { isError: true, content: [{ type: 'text', text: 'Internal server error. This is a bug.' }] };
    }

    const detail = isError(exception) ? (exception.stack ?? exception.message) : String(exception);
    this.logger.error('[MCP] Unexpected error:', detail);
    return { isError: true, content: [{ type: 'text', text: 'An unexpected error occurred.' }] };
  }
}
