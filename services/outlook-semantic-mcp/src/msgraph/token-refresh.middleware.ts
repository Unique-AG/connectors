import { isUpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { Context, Middleware } from '@microsoft/microsoft-graph-client';
import { Logger } from '@nestjs/common';
import { isObjectType } from 'remeda';
import { z } from 'zod';
import { toGraphPathTemplate } from './graph-path-template';
import { TokenProvider, TokenRefreshCoolingDownError } from './token.provider';

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
    if (response?.status !== 401) {
      return false;
    }

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
    if (typeof request === 'string') {
      return request;
    }
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

  private getRejectedAccessToken(options: RequestInit | undefined): string | undefined {
    const headers = options?.headers;
    const authorization =
      headers instanceof Headers
        ? headers.get('Authorization')
        : isObjectType(headers) &&
            'Authorization' in headers &&
            typeof headers.Authorization === 'string'
          ? headers.Authorization
          : undefined;
    return authorization?.replace(/^Bearer /, '');
  }

  // Only the Graph error code is read; the message and innerError carry mailbox addresses,
  // request ids and client request ids.
  private async getGraphErrorCode(response: Response | undefined): Promise<string | undefined> {
    try {
      const body: unknown = await response?.clone().json();
      return GraphErrorBodySchema.safeParse(body).data?.error.code;
    } catch {
      return undefined;
    }
  }

  public async execute(context: Context): Promise<void> {
    if (!this.nextMiddleware) {
      throw new Error('Next middleware not set');
    }

    // Execute the request for the first time
    await this.nextMiddleware.execute(context);

    const isExpired = await this.isTokenExpiredError(context.response);
    if (!isExpired) {
      return;
    }

    this.logger.debug({
      msg: 'Microsoft Graph access token has expired for user, attempting refresh',
      userProfileId: this.userProfileId,
      tokenStatus: 'expired',
      action: 'refresh_attempt',
    });

    try {
      const newAccessToken = await this.tokenProvider.refreshAccessToken(
        this.userProfileId,
        this.getRejectedAccessToken(context.options),
      );
      this.logger.debug({
        msg: 'Successfully refreshed expired Microsoft Graph access token for user',
        userProfileId: this.userProfileId,
        tokenStatus: 'refreshed',
        action: 'refresh_success',
      });

      const clonedRequest = this.cloneRequest(context.request, context.options);
      const updatedOptions = this.updateAuthorizationHeader(context.options, newAccessToken);

      const retryContext: Context = {
        request: clonedRequest,
        options: updatedOptions,
        middlewareControl: context.middlewareControl,
        customHosts: context.customHosts,
      };

      this.logger.debug({
        msg: 'Retrying Microsoft Graph request with newly refreshed access token',
        userProfileId: this.userProfileId,
        action: 'retry_request',
        tokenStatus: 'fresh',
      });
      await this.nextMiddleware.execute(retryContext);

      context.response = retryContext.response;

      if (context.response?.ok) {
        this.logger.debug({
          msg: 'Microsoft Graph request succeeded after token refresh was completed',
          userProfileId: this.userProfileId,
          retryResult: 'success',
          tokenRefreshWorked: true,
        });
      } else {
        this.logger.warn({
          msg: 'Microsoft Graph request failed even after successful token refresh',
          userProfileId: this.userProfileId,
          retryResult: 'failed',
          tokenRefreshWorked: false,
          retryStatus: context.response?.status,
          graphErrorCode: await this.getGraphErrorCode(context.response),
          method: context.options?.method?.toUpperCase() ?? 'GET',
          path: toGraphPathTemplate(context.request),
        });
      }
    } catch (err) {
      // TokenProvider has already logged this and revoked the MCP tokens, so propagate rather
      // than keeping the original 401 response.
      if (isUpstreamCredentialRevokedError(err)) {
        throw err;
      }
      if (err instanceof TokenRefreshCoolingDownError) {
        this.logger.debug({
          msg: 'Skipped Microsoft Graph token refresh while backing off after a failed refresh',
          userProfileId: this.userProfileId,
          retryAt: err.retryAt.toISOString(),
        });
        return;
      }
      this.logger.error({
        msg: 'Failed to refresh token or retry Microsoft Graph request for user',
        userProfileId: this.userProfileId,
        tokenRefreshFailed: true,
        err,
      });
      // Keep the original 401 response if a transient refresh fails.
      // Permanent grant failures are rethrown above so the MCP session can be revoked.
    }
  }

  public setNext(next: Middleware): void {
    this.nextMiddleware = next;
  }
}

const GraphErrorBodySchema = z.object({ error: z.object({ code: z.string() }) });
