import { Context, Middleware } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { TokenProvider } from './token.provider';

export class TokenRefreshMiddleware implements Middleware {
  private readonly logger = new Logger(this.constructor.name);

  private nextMiddleware: Middleware | undefined;
  private userProfileId: string;

  public constructor(
    private readonly tokenProvider: TokenProvider,
    userProfileId: string,
  ) {
    this.userProfileId = userProfileId;
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
        errorBody?.error?.message?.includes('token is expired')
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

  public async execute(context: Context): Promise<void> {
    if (!this.nextMiddleware) throw new Error('Next middleware not set');

    // Execute the request for the first time
    await this.nextMiddleware.execute(context);

    const isExpired = await this.isTokenExpiredError(context.response);
    if (!isExpired) return;

    this.logger.debug(
      {
        userProfileId: this.userProfileId,
        tokenStatus: 'expired',
        action: 'refresh_attempt',
      },
      'Microsoft Graph access token has expired for user, attempting refresh',
    );

    try {
      const newAccessToken = await this.tokenProvider.refreshAccessToken(this.userProfileId);
      this.logger.debug(
        {
          userProfileId: this.userProfileId,
          tokenStatus: 'refreshed',
          action: 'refresh_success',
        },
        'Successfully refreshed expired Microsoft Graph access token for user',
      );

      const clonedRequest = this.cloneRequest(context.request, context.options);
      const updatedOptions = this.updateAuthorizationHeader(context.options, newAccessToken);

      const retryContext: Context = {
        request: clonedRequest,
        options: updatedOptions,
        middlewareControl: context.middlewareControl,
        customHosts: context.customHosts,
      };

      this.logger.debug(
        {
          userProfileId: this.userProfileId,
          action: 'retry_request',
          tokenStatus: 'fresh',
        },
        'Retrying Microsoft Graph request with newly refreshed access token',
      );
      await this.nextMiddleware.execute(retryContext);

      context.response = retryContext.response;

      if (context.response?.ok) {
        this.logger.debug(
          {
            userProfileId: this.userProfileId,
            retryResult: 'success',
            tokenRefreshWorked: true,
          },
          'Microsoft Graph request succeeded after token refresh was completed',
        );
      } else {
        this.logger.warn(
          {
            userProfileId: this.userProfileId,
            retryResult: 'failed',
            tokenRefreshWorked: false,
          },
          'Microsoft Graph request failed even after successful token refresh',
        );
      }
    } catch (error) {
      this.logger.error({
        msg: 'Failed to refresh token or retry Microsoft Graph request for user',
        userProfileId: this.userProfileId,
        tokenRefreshFailed: true,
        error,
      });
      // Keep the original 401 response if refresh fails
      // The calling code will handle the authentication error appropriately
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }
}
