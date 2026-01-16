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

    const status = exception.statusCode || HttpStatus.INTERNAL_SERVER_ERROR;

    this.logger.error(
      {
        statusCode: exception.statusCode,
        code: exception.code,
        requestId: exception.requestId,
        date: exception.date,
        body: exception.body,
        message: exception.message,
      },
      `Microsoft Graph API error: ${exception.code ?? exception.message}`,
    );

    response.status(status).json({
      statusCode: status,
      error: 'Microsoft Graph API Error',
      code: exception.code,
      message: exception.message,
      requestId: exception.requestId,
      timestamp: exception.date?.toISOString(),
    });
  }
}
