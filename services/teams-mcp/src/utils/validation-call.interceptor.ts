import {
  type CallHandler,
  type ExecutionContext,
  HttpStatus,
  Injectable,
  Logger,
  type NestInterceptor,
} from '@nestjs/common';
import type { Request, Response } from 'express';
import { of } from 'rxjs';

/**
 * Interceptor to handle validation calls from Microsoft.
 *
 * @see https://learn.microsoft.com/en-us/graph/api/subscription-post-subscriptions?view=graph-rest-1.0&tabs=http
 */
@Injectable()
export class ValidationCallInterceptor implements NestInterceptor {
  private readonly logger = new Logger(ValidationCallInterceptor.name);

  public intercept(context: ExecutionContext, next: CallHandler) {
    const request = context.switchToHttp().getRequest<Request>();
    const response = context.switchToHttp().getResponse<Response>();

    const validationToken = request.query.validationToken;
    if (typeof validationToken === 'string') {
      this.logger.debug(
        {
          validationToken,
          path: request.path,
        },
        'Validation call received for subscription',
      );
      response.status(HttpStatus.OK).contentType('text/plain');
      return of(validationToken);
    }

    return next.handle();
  }
}
