import { type ArgumentsHost, Catch, type ExceptionFilter, HttpStatus } from '@nestjs/common';
import type { Response } from 'express';
import { UniqueInternalError } from './unique-internal.error.js';

const statuses: Record<UniqueInternalError['code'], HttpStatus> = {
  UNAUTHORIZED: HttpStatus.FORBIDDEN,
  NOT_FOUND: HttpStatus.NOT_FOUND,
  CONFLICT: HttpStatus.CONFLICT,
  UNAVAILABLE: HttpStatus.SERVICE_UNAVAILABLE,
  INVALID_RESPONSE: HttpStatus.BAD_GATEWAY,
  TOO_LARGE: HttpStatus.PAYLOAD_TOO_LARGE,
};

/** Core decides access: its denials surface as 403/404, never as internal errors or details. */
@Catch(UniqueInternalError)
export class UniqueInternalErrorFilter implements ExceptionFilter {
  public catch(error: UniqueInternalError, host: ArgumentsHost): void {
    const statusCode = statuses[error.code];
    host
      .switchToHttp()
      .getResponse<Response>()
      .status(statusCode)
      .json({ statusCode, message: HttpStatus[statusCode] });
  }
}
