import { type ArgumentsHost, Catch, type ExceptionFilter, HttpException, Logger } from '@nestjs/common';
import type { Response } from 'express';
import { isError } from 'remeda';
import { DefectError } from '../errors/defect.js';
import { McpBaseError } from '../errors/base.js';
import { UpstreamConnectionRequiredError } from '../errors/failures.js';

/**
 * HTTP-layer exception filter applied to MCP server endpoints. Maps error types to HTTP responses:
 * - `HttpException` → its own status code and body
 * - `UpstreamConnectionRequiredError` → 401 with reconnect URL
 * - `McpBaseError` → 400 with MCP error code
 * - `DefectError` / unexpected → 500 with JSON-RPC internal error code (-32603)
 */
@Catch()
export class McpHttpExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(McpHttpExceptionFilter.name);

  public catch(error: unknown, host: ArgumentsHost): void {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();

    if (error instanceof HttpException) {
      response.status(error.getStatus()).json(error.getResponse());
      return;
    }

    if (error instanceof UpstreamConnectionRequiredError) {
      this.logger.warn(`Upstream connection required: ${error.upstreamName}`);
      response.status(401).json({
        code: -32001,
        message: error.message,
        data: { reconnectUrl: error.reconnectUrl },
      });
      return;
    }

    if (error instanceof McpBaseError) {
      this.logger.warn(`[${error.errorCode}] ${error.message}`);
      response.status(400).json({
        code: error.metadata.mcpErrorCode ?? -32000,
        message: error.message,
      });
      return;
    }

    if (error instanceof DefectError) {
      this.logger.error('Defect encountered', error.stack);
      response.status(500).json({ code: -32603, message: 'Internal server error' });
      return;
    }

    const stack = isError(error) ? error.stack : String(error);
    this.logger.error('Unexpected error', stack);
    response.status(500).json({ code: -32603, message: 'Internal server error' });
  }
}
