import {
  ArgumentsHost,
  Catch,
  ExceptionFilter,
  HttpStatus,
  Inject,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import type { Response } from 'express';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
} from '../mcp-oauth.module-definition';

/**
 * Exception filter for OAuth-related unauthorized errors.
 * Implements RFC9728 Section 5.1 "WWW-Authenticate Response" for protected resources.
 */
@Catch(UnauthorizedException)
export class OAuthExceptionFilter implements ExceptionFilter {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
  ) {}

  public catch(exception: UnauthorizedException, host: ArgumentsHost): void {
    const ctx = host.switchToHttp();
    const response = ctx.getResponse<Response>();
    const request = ctx.getRequest();

    this.logger.debug({
      msg: 'Handling unauthorized exception',
      url: request.url,
      path: request.path,
      message: exception.message,
    });

    if (request.url?.startsWith('/mcp')) {
      const resourceMetadataUrl = `${this.options.serverUrl}/.well-known/oauth-protected-resource/mcp`;

      let wwwAuthenticate = `Bearer resource_metadata="${resourceMetadataUrl}"`;

      const errorMessage = exception.message || 'The access token is invalid or expired';
      const errorCode = this.getErrorCode(errorMessage);

      if (errorCode) {
        wwwAuthenticate += `, error="${errorCode}"`;
        wwwAuthenticate += `, error_description="${errorMessage}"`;
      }

      if (this.options.resource) {
        wwwAuthenticate += `, realm="${this.options.resource}"`;
      }

      response
        .status(HttpStatus.UNAUTHORIZED)
        .header('WWW-Authenticate', wwwAuthenticate)
        .json({
          error: errorCode || 'invalid_token',
          error_description: errorMessage,
          ...(this.options.serverUrl && {
            error_uri: `${this.options.serverUrl}/docs/errors/${errorCode || 'invalid_token'}`,
          }),
        });
    } else {
      response.status(HttpStatus.UNAUTHORIZED).json({
        statusCode: HttpStatus.UNAUTHORIZED,
        message: exception.message || 'Unauthorized',
        error: 'Unauthorized',
      });
    }
  }

  /**
   * Maps exception messages to OAuth 2.0 error codes
   * Based on RFC6750 Section 3.1
   */
  private getErrorCode(message: string): string {
    const lowerMessage = message.toLowerCase();

    if (lowerMessage.includes('expired')) {
      return 'invalid_token';
    }

    if (lowerMessage.includes('invalid') || lowerMessage.includes('malformed')) {
      return 'invalid_token';
    }

    if (lowerMessage.includes('required') || lowerMessage.includes('missing')) {
      return 'invalid_request';
    }

    if (lowerMessage.includes('insufficient') || lowerMessage.includes('scope')) {
      return 'insufficient_scope';
    }

    return 'invalid_token';
  }
}
