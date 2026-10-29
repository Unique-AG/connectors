import { randomBytes } from 'node:crypto';
import {
  BadRequestException,
  Body,
  Controller,
  ForbiddenException,
  Get,
  HttpStatus,
  Inject,
  Logger,
  Next,
  Post,
  Query,
  Req,
  Res,
  UnauthorizedException,
  UseGuards,
  UsePipes,
} from '@nestjs/common';
import { seconds, Throttle, ThrottlerGuard } from '@nestjs/throttler';
import { type NextFunction, type Request, type Response } from 'express';
import { ZodValidationPipe } from 'nestjs-zod';
import passport from 'passport';
import { serializeError } from 'serialize-error-cjs';
import { OAUTH_ENDPOINTS } from '../constants/oauth.constants';
import { ConsentDecisionDto } from '../dtos/consent-decision.dto';
import type { IOAuthStore } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { ClientService } from '../services/client.service';
import { FlowBindingService } from '../services/flow-binding.service';
import { McpOAuthService } from '../services/mcp-oauth.service';
import { MetricService } from '../services/metric.service';
import { PassportUser, STRATEGY_NAME } from '../services/oauth-strategy.service';
import { CONSENT_PAGE_HEADERS, renderConsentPage } from '../utils/consent-page';
import { normalizeError } from '../utils/normalize-error';
import { decodeProviderState } from '../utils/provider-state';

@Controller()
@UseGuards(ThrottlerGuard)
export class OAuthController {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
    private readonly authService: McpOAuthService,
    private readonly clientService: ClientService,
    @Inject(OAUTH_STORE_TOKEN) private readonly store: IOAuthStore,
    private readonly metricService: MetricService,
    private readonly flowBinding: FlowBindingService,
  ) {}

  @Get(OAUTH_ENDPOINTS.authorize)
  @Throttle({ auth: { limit: 3, ttl: seconds(60) } })
  public async authorize(
    @Query('response_type') responseType: string,
    @Query('client_id') clientId: string,
    @Query('redirect_uri') redirectUri: string,
    @Query('code_challenge') codeChallenge: string,
    @Query('code_challenge_method') codeChallengeMethod: string,
    @Query('state') state: string,
    @Query('scope') scope: string,
    @Query('resource') resource: string,
    @Res() response: Response,
  ) {
    this.logger.debug({
      msg: 'Start oAuth autorization',
      clientId,
      redirectUri,
      resource,
    });

    if (responseType !== 'code') {
      throw new BadRequestException('Invalid response type');
    }
    if (!clientId) {
      throw new BadRequestException('Missing client_id parameter');
    }

    this.metricService.incrementFlowsStarted();

    // Validate resource parameter according to RFC 8707
    // The resource parameter MUST identify the MCP server that the client intends to use the token with
    if (resource && resource !== this.options.resource) {
      this.logger.error({
        msg: 'Invalid resource parameter',
        requested: resource,
        expected: this.options.resource,
      });
      throw new BadRequestException('Invalid resource parameter');
    }

    const client = await this.clientService.getClient(clientId);
    if (!client) {
      throw new BadRequestException('Invalid client_id parameter');
    }

    const validRedirectUri = await this.clientService.validateRedirectUri(clientId, redirectUri);
    if (!validRedirectUri) {
      throw new BadRequestException('Invalid redirect_uri parameter');
    }

    // OAuth 2.1 compliance: PKCE is mandatory for all clients
    if (!codeChallenge) {
      this.logger.error({
        msg: 'PKCE code_challenge is required for OAuth 2.1 compliance',
        clientId,
      });
      throw new BadRequestException('code_challenge parameter is required');
    }

    if (!codeChallengeMethod) {
      this.logger.error({
        msg: 'PKCE code_challenge_method is required for OAuth 2.1 compliance',
        clientId,
      });
      throw new BadRequestException('code_challenge_method parameter is required');
    }

    // Validate code_challenge_method
    if (codeChallengeMethod !== 'S256') {
      this.logger.error({
        msg: 'Only S256 code_challenge_method is supported for OAuth 2.1 compliance',
        clientId,
        codeChallengeMethod,
      });
      throw new BadRequestException('code_challenge_method must be S256');
    }

    const sessionId = randomBytes(32).toString('base64url');
    await this.store.storeOAuthSession(sessionId, {
      sessionId,
      // Replaced by a signed state once the user approves, see McpOAuthService.approveConsent.
      state: randomBytes(32).toString('base64url'),
      clientId,
      redirectUri,
      codeChallenge,
      codeChallengeMethod,
      oauthState: state, // This is the PKCE state of the MCP client.
      scope,
      resource: resource || this.options.resource,
      expiresAt: Date.now() + this.options.oauthSessionExpiresIn,
    });

    const { cookie, csrfToken } = this.flowBinding.createBinding(sessionId);

    this.logger.debug({
      msg: 'New session created. Asking the user to approve the client.',
      redirectUri,
      sessionId,
    });

    response
      .cookie(cookie.name, cookie.value, cookie.options)
      .set(CONSENT_PAGE_HEADERS)
      .status(HttpStatus.OK)
      .send(
        renderConsentPage({
          clientName: client.client_name,
          redirectUri,
          resourceName:
            this.options.protectedResourceMetadata.resourceName ??
            new URL(this.options.resource).host,
          formAction: `${this.options.serverUrl}${OAUTH_ENDPOINTS.consent}`,
          sessionId,
          csrfToken,
        }),
      );
  }

  @Post(OAUTH_ENDPOINTS.consent)
  @Throttle({ default: { limit: 5, ttl: seconds(60) } })
  @UsePipes(ZodValidationPipe)
  public async consent(
    @Body() { session_id: sessionId, csrf_token: csrfToken, decision }: ConsentDecisionDto,
    @Req() request: Request,
    @Res() response: Response,
    @Next() next: NextFunction,
  ) {
    const cookieValue = this.flowBinding.readBinding(request.headers.cookie, sessionId);
    if (!cookieValue || !this.flowBinding.isValidCsrfToken(sessionId, cookieValue, csrfToken)) {
      this.logger.warn({ msg: 'Consent submitted without a valid flow cookie or CSRF token' });
      throw new ForbiddenException('This sign-in was not started in this browser.');
    }

    const session = await this.store.getOAuthSession(sessionId);
    if (!session?.redirectUri || session.expiresAt < Date.now()) {
      throw new BadRequestException('Invalid or expired OAuth session.');
    }

    if (decision === 'deny') {
      const { name, options } = this.flowBinding.clearedCookie(sessionId);
      const redirectUrl = await this.authService.denyConsent(session);
      this.logger.debug({ msg: 'User denied the client.', sessionId });
      return response.clearCookie(name, options).redirect(redirectUrl);
    }

    const providerState = await this.authService.approveConsent(session);
    this.logger.debug({ msg: 'User approved the client. Redirecting to the provider.', sessionId });

    const authMiddleware = passport.authenticate(STRATEGY_NAME, { state: providerState });
    authMiddleware(request, response, next);
  }

  @Get(OAUTH_ENDPOINTS.callback)
  @Throttle({ default: { limit: 5, ttl: seconds(60) } })
  public async callback(
    @Query('state') state: string,
    @Req() request: Request,
    @Res() response: Response,
    @Next() next: NextFunction,
  ) {
    const providerState = decodeProviderState(state);
    if (
      !providerState ||
      !this.flowBinding.readBinding(request.headers.cookie, providerState.sessionId)
    ) {
      this.logger.warn({ msg: 'Provider callback without a valid flow cookie' });
      return response.status(HttpStatus.UNAUTHORIZED).json({
        error: 'Authentication failed',
        error_description: 'This sign-in was not started in this browser.',
      });
    }

    const { name, options } = this.flowBinding.clearedCookie(providerState.sessionId);
    response.clearCookie(name, options);

    const authMiddleware = passport.authenticate(
      STRATEGY_NAME,
      { session: false },
      // biome-ignore lint/suspicious/noExplicitAny: Any is the official type for the info parameter.
      async (error: unknown, user: PassportUser, info: any) => {
        try {
          if (error) {
            this.logger.error({
              msg: 'Failed to authenticate user',
              error: serializeError(normalizeError(error)),
            });
            const errorMessage =
              typeof error === 'object' && error !== null && 'message' in error
                ? (error as { message: string }).message
                : 'Authentication failed';
            throw new UnauthorizedException(errorMessage);
          }

          if (!user) {
            // When strategy calls fail(), the error info is passed in the info parameter
            const failureMessage = info?.message || 'Authentication failed';
            throw new UnauthorizedException(failureMessage);
          }

          this.logger.debug({ msg: 'User authenticated.' });

          request.user = user;
          const { redirectUrl } = await this.authService.processAuthenticationSuccess({
            user,
            ...providerState,
          });

          this.logger.debug({
            msg: 'User JWT created and oauth session cleared. Redirecting the user back to the MCP client.',
            redirectUrl,
          });

          return response.redirect(redirectUrl);
        } catch (error) {
          this.logger.error({
            msg: 'Failed to authenticate user',
            error: serializeError(normalizeError(error)),
          });

          const { redirectUrl, errorMessage } = await this.authService.processAuthenticationError({
            error,
            state,
          });

          if (redirectUrl) {
            this.logger.debug({
              msg: 'Redirecting user to client with error parameters',
              redirectUrl,
            });

            return response.redirect(redirectUrl);
          }

          // Fallback to JSON response if we can't redirect
          return response.status(HttpStatus.UNAUTHORIZED).json({
            error: 'Authentication failed',
            error_description: errorMessage,
          });
        }
      },
    );

    authMiddleware(request, response, next);
  }
}
