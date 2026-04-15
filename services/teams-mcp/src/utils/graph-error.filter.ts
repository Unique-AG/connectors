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
 * MS Graph SDK bug: `.getStream()` error responses leave `GraphError.body` as
 * an unconsumed ReadableStream instead of parsed JSON. The SDK's
 * `GraphResponseHandler` converts the body using the requested responseType
 * (STREAM) *before* checking `rawResponse.ok`, so the JSON error is never parsed.
 *
 * This function consumes the stream and backfills code/message/requestId on the
 * exception so the filter can log them. Mirrors the SDK's internal parsing from
 * `GraphErrorHandler.constructErrorFromResponse` (which is not publicly exported).
 */
async function hydrateStreamBody(exception: GraphError): Promise<void> {
  if (!(exception.body instanceof ReadableStream)) {
    return;
  }

  try {
    const text = await new Response(exception.body).text();
    const parsed = JSON.parse(text);
    const error = parsed?.error;

    if (error) {
      exception.code ??= error.code ?? null;
      exception.message ||= error.message ?? '';
      exception.requestId ??= error.innerError?.['request-id'] ?? null;
      exception.body = JSON.stringify(error);
    } else {
      exception.body = text;
    }
  } catch {
    exception.body = null;
  }
}

/**
 * Exception filter to handle Microsoft Graph API errors.
 *
 * Catches GraphError exceptions and formats them into structured log output
 * and HTTP responses with relevant details from the Graph API error.
 */
@Catch(GraphError)
export class GraphErrorFilter implements ExceptionFilter {
  private readonly logger = new Logger(GraphErrorFilter.name);

  public async catch(exception: GraphError, host: ArgumentsHost) {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();

    await hydrateStreamBody(exception);

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

    // Pass through the Graph API status code so MCP clients can react appropriately —
    // e.g., a 401 lets the client retrigger authentication. Fall back to 500 for unknown codes.
    // GraphError initializes statusCode to -1 (not null/undefined) when no HTTP status is available,
    // so we validate the range rather than using ??.
    const isValidHttpStatus = exception.statusCode >= 100 && exception.statusCode <= 599;
    const statusCode = isValidHttpStatus ? exception.statusCode : HttpStatus.INTERNAL_SERVER_ERROR;
    response.status(statusCode).json({
      error: 'Microsoft Graph API Error',
      code: exception.code,
      message: exception.message,
      requestId: exception.requestId,
      timestamp: exception.date?.toISOString(),
    });
  }
}
