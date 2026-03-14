import { GraphError } from '@microsoft/microsoft-graph-client';
import {
  type ArgumentsHost,
  Catch,
  type ExceptionFilter,
  HttpStatus,
  Logger,
} from '@nestjs/common';
import type { Response } from 'express';

export interface SafeGraphErrorInfo {
  message: string;
  code?: string;
  statusCode?: number;
}

export function extractSafeGraphError(error: unknown): SafeGraphErrorInfo {
  if (error instanceof GraphError) {
    return {
      message: error.message,
      code: error.code ?? undefined,
      statusCode: error.statusCode,
    };
  }
  if (error instanceof Error) {
    return { message: error.message };
  }
  return { message: 'An unexpected error occurred' };
}

@Catch(GraphError)
export class GraphErrorFilter implements ExceptionFilter {
  private readonly logger = new Logger(GraphErrorFilter.name);

  public catch(exception: GraphError, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();

    const formattedCode = exception.code ? `[${exception.code ?? ''}] ` : ' ';
    this.logger.error(
      {
        statusCode: exception.statusCode,
        code: exception.code,
        requestId: exception.requestId,
        date: exception.date,
        body: exception.body,
        message: exception.message,
      },
      `${formattedCode}Microsoft Graph API: ${exception.message}`,
    );

    response.status(HttpStatus.INTERNAL_SERVER_ERROR).json({
      error: 'Microsoft Graph API Error',
      code: exception.code,
      message: exception.message,
      requestId: exception.requestId,
      timestamp: exception.date?.toISOString(),
    });
  }
}
