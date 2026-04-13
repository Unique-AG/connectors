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
