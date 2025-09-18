import { Context, Middleware } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { GraphAuthenticationProvider } from './graph-authentication.service';

/**
 * Token refresh middleware for Microsoft Graph requests
 * Handles token expiration
 */
export class TokenRefreshMiddleware implements Middleware {
  private readonly logger = new Logger(this.constructor.name);
  private nextMiddleware: Middleware | undefined;

  public constructor(private readonly graphAuthenticationProvider: GraphAuthenticationProvider) {}

  public async execute(context: Context): Promise<void> {
    if (!this.nextMiddleware) throw new Error('Next middleware not set');

    // Execute the request for the first time
    await this.nextMiddleware.execute(context);

    const isExpired = await this.isTokenExpiredError(context.response);
    if (!isExpired) return;

    this.logger.debug('SharePoint token expired, attempting to refresh...');

    try {
      // Force refresh the token (client credentials flow doesn't have refresh tokens,
      // but we can get a new access token)
      const newAccessToken = await this.graphAuthenticationProvider.getAccessToken();
      this.logger.debug('Successfully refreshed SharePoint token');

      const clonedRequest = this.cloneRequest(context.request, context.options);
      const updatedOptions = this.updateAuthorizationHeader(context.options, newAccessToken);

      const retryContext: Context = {
        request: clonedRequest,
        options: updatedOptions,
        middlewareControl: context.middlewareControl,
        customHosts: context.customHosts,
      };

      this.logger.debug('Retrying SharePoint request with refreshed token');
      await this.nextMiddleware.execute(retryContext);

      context.response = retryContext.response;

      if (context.response?.ok) {
        this.logger.debug('SharePoint request succeeded after token refresh');
      } else {
        this.logger.warn({
          msg: 'SharePoint request still failed after token refresh',
          status: context.response?.status,
        });
      }
    } catch (error) {
      this.logger.error({
        msg: 'Failed to refresh SharePoint token or retry request',
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }

  private async isTokenExpiredError(response: Response | undefined): Promise<boolean> {
    if (response?.status !== 401) return false;

    try {
      // Clone the response to read the body without consuming it
      const clonedResponse = response.clone();
      const errorBody = await clonedResponse.json();

      // Check for specific InvalidAuthenticationToken error
      return (
        errorBody?.error?.code === 'InvalidAuthenticationToken' ||
        errorBody?.error?.message?.includes('Lifetime validation failed') ||
        errorBody?.error?.message?.includes('token is expired') ||
        errorBody?.error?.message?.includes('Access token has expired')
      );
    } catch {
      // If we can't parse the body, just check for 401 status
      return response.status === 401;
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
