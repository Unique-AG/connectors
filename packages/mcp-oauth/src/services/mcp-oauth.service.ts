import { createHash, createHmac, randomBytes } from 'node:crypto';
import {
  BadRequestException,
  Inject,
  Injectable,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import {
  type IntrospectionResponse,
  type IntrospectRequestDto,
} from '../dtos/introspect-request.dto';
import { type RevokeRequestDto } from '../dtos/revoke-request.dto';
import { TokenRequestDto } from '../dtos/token-request.dto';
import type { IOAuthStore } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { ClientService } from './client.service';
import { IDTokenService } from './id-token.service';
import { PassportUser } from './oauth-strategy.service';
import { OpaqueTokenService } from './opaque-token.service';

@Injectable()
export class McpOAuthService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
    @Inject(OAUTH_STORE_TOKEN) private readonly store: IOAuthStore,
    private readonly tokenService: OpaqueTokenService,
    private readonly clientService: ClientService,
    private readonly idTokenService: IDTokenService,
  ) {}

  public async processAuthenticationSuccess({
    user,
    sessionId,
    sessionNonce,
    sessionHmac,
  }: {
    user: PassportUser;
    sessionId: string;
    sessionNonce: string;
    sessionHmac: string;
  }) {
    this.logger.debug({
      msg: 'Processing authentication success',
      sessionId,
    });

    if (!user) throw new UnauthorizedException('Authentication failed');
    if (!sessionId) throw new UnauthorizedException('Authentication failed');

    const session = await this.store.getOAuthSession(sessionId);
    if (!session) throw new UnauthorizedException('Invalid or expired OAuth session.');
    if (
      !session.clientId ||
      !session.redirectUri ||
      !session.codeChallenge ||
      !session.codeChallengeMethod
    )
      throw new UnauthorizedException('Invalid or expired OAuth session.');

    if (session.state !== sessionHmac) throw new UnauthorizedException('Invalid state.');

    const expectedHmac = createHmac('sha256', this.options.hmacSecret)
      .update(`${session.sessionId}:${sessionNonce}`)
      .digest('base64url');
    if (sessionHmac !== expectedHmac) throw new UnauthorizedException('Invalid state validation.');

    const userProfileId = await this.store.upsertUserProfile(user);
    const authCode = randomBytes(32).toString('base64url');

    this.logger.debug({
      msg: 'Session PKCE validated, user profile upserted, auth code generated.',
      userProfileId,
      sessionId: session.sessionId,
    });

    await this.store.storeAuthCode({
      code: authCode,
      user_id: user.profile.username,
      client_id: session.clientId,
      redirect_uri: session.redirectUri,
      code_challenge: session.codeChallenge,
      code_challenge_method: session.codeChallengeMethod,
      expires_at: Date.now() + this.options.authCodeExpiresIn,
      resource: session.resource,
      scope: session.scope,
      user_profile_id: userProfileId,
    });

    // Build redirect URL with authorization code
    const redirectUrl = new URL(session.redirectUri);
    redirectUrl.searchParams.set('code', authCode);
    if (session.oauthState) redirectUrl.searchParams.set('state', session.oauthState);

    await this.store.removeOAuthSession(sessionId);

    return {
      redirectUrl: redirectUrl.toString(),
    };
  }

  public async processAuthenticationError({
    error,
    state,
  }: {
    error: unknown;
    state?: string;
  }): Promise<{ redirectUrl: string | null; errorMessage: string }> {
    this.logger.debug({
      msg: 'Processing authentication error',
      hasState: !!state,
    });

    const errorMessage =
      typeof error === 'object' && error !== null && 'message' in error
        ? (error as { message: string }).message
        : 'Authentication failed';

    if (!state) return { redirectUrl: null, errorMessage };

    let redirectUri: string | null = null;
    let oauthState: string | null = null;

    try {
      const decodedState = JSON.parse(Buffer.from(state, 'base64url').toString('utf-8'));
      const { sessionId } = decodedState;

      if (sessionId) {
        const session = await this.store.getOAuthSession(sessionId);
        if (session?.redirectUri) {
          redirectUri = session.redirectUri;
          oauthState = session.oauthState || null;

          // Clean up the session since we're handling the error
          await this.store.removeOAuthSession(sessionId);

          this.logger.debug({
            msg: 'Session found and cleaned up for error redirect',
            sessionId,
            redirectUri,
          });
        }
      }
    } catch (sessionError) {
      this.logger.debug({
        msg: 'Could not extract session info for error redirect',
        error: sessionError instanceof Error ? sessionError.message : 'Unknown error',
      });
    }

    if (!redirectUri) return { redirectUrl: null, errorMessage };

    const errorRedirectUrl = new URL(redirectUri);
    errorRedirectUrl.searchParams.set('error', 'access_denied');
    errorRedirectUrl.searchParams.set('error_description', errorMessage);

    if (oauthState) errorRedirectUrl.searchParams.set('state', oauthState);

    return {
      redirectUrl: errorRedirectUrl.toString(),
      errorMessage,
    };
  }

  public async exchangeAuthorizationCodeForToken(tokenDto: TokenRequestDto) {
    const { code, client_id, client_secret, code_verifier, resource } = tokenDto;

    // 1. Validate the authorization code
    if (!code) throw new BadRequestException('Missing code parameter');

    // Immediately consume the code (single-use enforcement)
    const authCode = await this.store.getAuthCode(code);
    if (authCode) {
      // Remove it immediately to prevent replay attacks
      await this.store.removeAuthCode(code);
    }

    if (!authCode) {
      this.logger.error({
        msg: 'Invalid or expired authorization code',
        code,
      });
      throw new BadRequestException('Invalid or expired authorization code');
    }

    if (authCode.expires_at < Date.now()) {
      this.logger.error({
        msg: 'Authorization code expired',
        code,
      });
      throw new BadRequestException('Invalid or expired authorization code');
    }

    if (authCode.client_id !== client_id) {
      this.logger.error({
        msg: 'Authorization code does not belong to the client',
        code,
        client_id,
      });
      throw new BadRequestException('Client ID mismatch');
    }

    if (!authCode.resource) {
      this.logger.error({
        msg: 'Authorization code is not associated with a resource',
        code,
        client_id,
      });
      throw new BadRequestException('Authorization code is not associated with a resource');
    }

    // Validate resource parameter according to RFC 8707
    // If the client includes a resource parameter, it must match the one from the authorization request
    if (resource && resource !== authCode.resource) {
      this.logger.error({
        msg: 'Resource parameter mismatch',
        requested: resource,
        expected: authCode.resource,
      });
      throw new BadRequestException('Resource parameter mismatch');
    }

    // 2. Validate the client credentials
    const isValidClient = await this.clientService.validateClientCredentials(
      client_id,
      client_secret,
    );
    if (!isValidClient) {
      this.logger.error({
        msg: 'Invalid client credentials',
        client_id,
      });
      throw new UnauthorizedException('Invalid client credentials');
    }

    // 3. Validate the PKCE (mandatory!)
    if (!authCode.code_challenge || !code_verifier)
      throw new BadRequestException('PKCE is required for all clients.');

    const isValid = this.validatePKCE(
      code_verifier,
      authCode.code_challenge,
      authCode.code_challenge_method,
    );

    if (!isValid) {
      this.logger.error({
        msg: 'PKCE validation failed',
        code_challenge_method: authCode.code_challenge_method,
      });
      throw new BadRequestException('Invalid request');
    }

    // 4. Generate tokens
    const tokenPair = await this.tokenService.generateTokenPair(
      authCode.user_id,
      client_id,
      authCode.scope,
      authCode.resource,
      authCode.user_profile_id,
    );

    // 5. Generate ID token if openid scope is present (OIDC compliance)
    const scopes = authCode.scope?.split(' ') || [];
    if (scopes.includes('openid')) {
      // Fetch user profile for claims if needed
      const userProfile = await this.store.getUserProfileById(authCode.user_profile_id);
      
      const idToken = this.idTokenService.generateIDToken({
        userId: authCode.user_id,
        clientId: client_id,
        scope: authCode.scope,
        userProfile: userProfile ? {
          username: userProfile.username,
          email: userProfile.email,
          displayName: userProfile.displayName,
          avatarUrl: userProfile.avatarUrl,
        } : undefined,
      });

      tokenPair.id_token = idToken;
      
      this.logger.debug({
        msg: 'ID token generated for OIDC',
        userId: authCode.user_id,
        scopes: authCode.scope,
      });
    }

    this.logger.debug({
      msg: 'Token pair generated',
      userId: authCode.user_id,
      hasIdToken: !!tokenPair.id_token,
    });

    return tokenPair;
  }

  public async exchangeRefreshTokenForToken(tokenDto: TokenRequestDto) {
    const { refresh_token, client_id, client_secret, scope } = tokenDto;

    if (!refresh_token) throw new BadRequestException('Missing refresh_token parameter');

    // Validate client credentials
    const isValidClient = await this.clientService.validateClientCredentials(
      client_id,
      client_secret,
    );
    if (!isValidClient) throw new BadRequestException('Invalid client credentials');

    // Get refresh token metadata first to access user profile ID
    const refreshTokenMetadata = await this.tokenService.validateRefreshToken(refresh_token);
    if (!refreshTokenMetadata) {
      throw new BadRequestException({
        error: 'invalid_grant',
        error_description: 'Invalid or expired refresh token',
      });
    }

    const tokenPair = await this.tokenService.refreshAccessToken(refresh_token, client_id, scope);
    if (!tokenPair) {
      // Check if this was due to scope validation failure
      if (refreshTokenMetadata.clientId === client_id && scope) {
        // Token is valid but scope validation failed
        throw new BadRequestException({
          error: 'invalid_scope',
          error_description: 'The requested scope exceeds the scope granted by the resource owner',
        });
      }
      throw new BadRequestException({
        error: 'invalid_grant',
        error_description: 'Invalid or expired refresh token',
      });
    }

    // Generate ID token if openid scope is present (OIDC compliance)
    const finalScope = scope || refreshTokenMetadata.scope;
    const scopes = finalScope?.split(' ') || [];
    if (scopes.includes('openid')) {
      // Fetch user profile for claims
      const userProfile = await this.store.getUserProfileById(refreshTokenMetadata.userProfileId);
      
      const idToken = this.idTokenService.generateIDToken({
        userId: refreshTokenMetadata.userId,
        clientId: client_id,
        scope: finalScope,
        userProfile: userProfile ? {
          username: userProfile.username,
          email: userProfile.email,
          displayName: userProfile.displayName,
          avatarUrl: userProfile.avatarUrl,
        } : undefined,
      });

      tokenPair.id_token = idToken;
      
      this.logger.debug({
        msg: 'ID token generated for refresh request',
        userId: refreshTokenMetadata.userId,
        scopes: finalScope,
      });
    }

    return tokenPair;
  }

  /**
   * Introspect a token to determine its current state and metadata.
   * Implements RFC 7662: OAuth 2.0 Token Introspection
   */
  public async introspectToken(
    introspectDto: IntrospectRequestDto,
  ): Promise<IntrospectionResponse> {
    const { token, token_type_hint, client_id, client_secret } = introspectDto;

    // Validate client authentication
    const isValidClient = await this.clientService.validateClientCredentials(
      client_id,
      client_secret,
    );
    if (!isValidClient) {
      this.logger.warn({
        msg: 'Client authentication failed for introspection',
        client_id,
      });
      return { active: false };
    }

    // Access Token
    if (!token_type_hint || token_type_hint === 'access_token') {
      const accessTokenResult = await this.tokenService.validateAccessToken(token);

      if (!accessTokenResult) return { active: false };

      if (accessTokenResult.clientId !== client_id) {
        this.logger.warn({
          msg: 'Client attempted to introspect token belonging to another client',
          requesting_client: client_id,
          token_client: accessTokenResult.clientId,
        });
        return { active: false };
      }

      return {
        active: true,
        scope: accessTokenResult.scope,
        client_id: accessTokenResult.clientId,
        username: accessTokenResult.userId,
        token_type: 'Bearer',
        // Additional metadata
        resource: accessTokenResult.resource,
        user_profile_id: accessTokenResult.userProfileId,
      };
    }

    // Refresh Token
    if (!token_type_hint || token_type_hint === 'refresh_token') {
      const refreshTokenResult = await this.tokenService.validateRefreshToken(token);

      if (!refreshTokenResult) return { active: false };

      if (refreshTokenResult.clientId !== client_id) {
        this.logger.warn({
          msg: 'Client attempted to introspect refresh token belonging to another client',
          requesting_client: client_id,
          token_client: refreshTokenResult.clientId,
        });
        return { active: false };
      }

      return {
        active: true,
        scope: refreshTokenResult.scope,
        client_id: refreshTokenResult.clientId,
        username: refreshTokenResult.userId,
        token_type: 'refresh_token',
        // Additional metadata
        resource: refreshTokenResult.resource,
        user_profile_id: refreshTokenResult.userProfileId,
      };
    }

    // Token not found or expired
    return { active: false };
  }

  /**
   * Revoke a token to invalidate it immediately.
   * Implements RFC 7009: OAuth 2.0 Token Revocation
   *
   * Note: Revocation is idempotent - revoking an already revoked token is a no-op.
   */
  public async revokeToken(revokeDto: RevokeRequestDto): Promise<void> {
    const { token, token_type_hint, client_id, client_secret } = revokeDto;

    const isValidClient = await this.clientService.validateClientCredentials(
      client_id,
      client_secret,
    );
    if (!isValidClient) {
      this.logger.warn({
        msg: 'Client authentication failed for revocation',
        client_id,
      });
      // Per RFC 7009, we don't indicate errors
      return;
    }

    // Access Token
    if (!token_type_hint || token_type_hint === 'access_token') {
      const accessTokenResult = await this.tokenService.validateAccessToken(token);

      if (!accessTokenResult) return;

      if (accessTokenResult.clientId !== client_id) {
        this.logger.warn({
          msg: 'Client attempted to revoke token belonging to another client',
          requesting_client: client_id,
          token_client: accessTokenResult.clientId,
        });
        return;
      }

      await this.store.removeAccessToken(token);
      this.logger.log({
        msg: 'Access token revoked',
        clientId: client_id,
        tokenPrefix: token.substring(0, 8),
      });
      return;
    }

    // Refresh Token
    if (!token_type_hint || token_type_hint === 'refresh_token') {
      const refreshTokenResult = await this.tokenService.validateRefreshToken(token);

      if (!refreshTokenResult) return;

      if (refreshTokenResult.clientId !== client_id) {
        this.logger.warn({
          msg: 'Client attempted to revoke refresh token belonging to another client',
          requesting_client: client_id,
          token_client: refreshTokenResult.clientId,
        });
        return;
      }

      // Revoke the entire token family for security
      if (refreshTokenResult.familyId && this.store.revokeTokenFamily) {
        await this.store.revokeTokenFamily(refreshTokenResult.familyId);
        this.logger.log({
          msg: 'Refresh token family revoked',
          clientId: client_id,
          familyId: refreshTokenResult.familyId,
          tokenPrefix: token.substring(0, 8),
        });
      } else {
        // Fallback to removing just this token if family revocation is not available
        await this.store.removeRefreshToken(token);
        this.logger.log({
          msg: 'Refresh token revoked (family revocation not available)',
          clientId: client_id,
          tokenPrefix: token.substring(0, 8),
        });
      }
      return;
    }

    // Token not found or already revoked - this is still a success per RFC 7009
    this.logger.debug({
      msg: 'Token revocation attempted for non-existent or already revoked token',
      clientId: client_id,
    });
  }

  private validatePKCE(codeVerifier: string, codeChallenge: string, codeChallengeMethod: string) {
    if (codeChallengeMethod === 'plain') return codeVerifier === codeChallenge;
    if (codeChallengeMethod === 'S256') {
      const hash = createHash('sha256').update(codeVerifier).digest('base64url');
      return hash === codeChallenge;
    }
    return false;
  }
}
