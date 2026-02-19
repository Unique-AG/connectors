import { GraphError } from '@microsoft/microsoft-graph-client';
import {
  type ArgumentsHost,
  Catch,
  type ExceptionFilter,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import type { Response } from 'express';

/**
 * Exception filter to handle Microsoft Graph API errors.
 *
 * Catches GraphError exceptions and formats them into structured log output
 * and HTTP responses with relevant details from the Graph API error.
 */
@Catch(GraphError)
export class GraphErrorFilter implements ExceptionFilter {
  private readonly logger = new Logger(GraphErrorFilter.name);

  public catch(exception: GraphError, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();

    const formattedCode = exception.code ? `[${exception.code ?? ''}] ` : ' ';
    this.logger.error({
      msg: `${formattedCode}Microsoft Graph API: ${exception.message}`,
      statusCode: exception.statusCode,
      code: exception.code,
      requestId: exception.requestId,
      date: exception.date,
      body: exception.body,
      message: exception.message,
    });

    // Always return 500 regardless of the Graph API's actual status code (e.g., 401/403).
    // These errors occur during internal async processing, so from the client's perspective
    // this is an internal server error. We intentionally don't expose the upstream status
    // to avoid leaking implementation details about our internal MS Graph API interactions.
    response.status(HttpStatus.INTERNAL_SERVER_ERROR).json({
      error: 'Microsoft Graph API Error',
      code: exception.code,
      message: exception.message,
      requestId: exception.requestId,
      timestamp: exception.date?.toISOString(),
    });
  }
}
