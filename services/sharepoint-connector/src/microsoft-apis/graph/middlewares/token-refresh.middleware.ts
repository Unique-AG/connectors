import { Context, Middleware } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { sanitizeError } from '../../../utils/normalize-error';
import { GraphAuthenticationService } from './graph-authentication.service';

export class TokenRefreshMiddleware implements Middleware {
  private readonly logger = new Logger(this.constructor.name);
  private nextMiddleware: Middleware | undefined;

  public constructor(private readonly graphAuthenticationService: GraphAuthenticationService) {}

  public async execute(context: Context): Promise<void> {
    if (!this.nextMiddleware) throw new Error('Next middleware not set');

    await this.nextMiddleware.execute(context);

    const isExpired = await this.isTokenExpiredError(context.response);
    if (!isExpired) return;

    try {
      const newAccessToken = await this.graphAuthenticationService.getAccessToken();

      const clonedRequest = this.cloneRequest(context.request, context.options);
      const updatedOptions = this.updateAuthorizationHeader(context.options, newAccessToken);

      const retryContext: Context = {
        request: clonedRequest,
        options: updatedOptions,
        middlewareControl: context.middlewareControl,
        customHosts: context.customHosts,
      };

      await this.nextMiddleware.execute(retryContext);

      context.response = retryContext.response;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to refresh SharePoint token or retry request',
        error: sanitizeError(error),
      });
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }

  private async isTokenExpiredError(response: Response | undefined): Promise<boolean> {
    if (response?.status !== 401) return false;

    // leaving try block here to make sure .json() doesn't crash the server on malformed response
    try {
      const clonedResponse = response.clone();
      const errorBody = await clonedResponse.json();

      // TODO add source of the example middlewares (they are taken from an official example)
      return (
        errorBody?.error?.code === 'InvalidAuthenticationToken' ||
        errorBody?.error?.message?.includes('Lifetime validation failed') ||
        errorBody?.error?.message?.includes('token is expired') ||
        errorBody?.error?.message?.includes('Access token has expired')
      );
    } catch {
      return true;
    }
  }

  private cloneRequest(request: RequestInfo, _options?: RequestInit): RequestInfo {
    if (typeof request === 'string') return request;
    return request.clone();
  }

  private updateAuthorizationHeader(
    options: RequestInit | undefined,
    newAccessToken: string,
  ): RequestInit {
    const updatedOptions = { ...options };
    updatedOptions.headers = {
      ...updatedOptions.headers,
      Authorization: `Bearer ${newAccessToken}`,
    };
    return updatedOptions;
  }
}
