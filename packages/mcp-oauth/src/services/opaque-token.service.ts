import { randomBytes } from 'node:crypto';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Cron, CronExpression } from '@nestjs/schedule';
import { typeid } from 'typeid-js';
import type { IOAuthStore, RefreshTokenMetadata } from '../interfaces/io-auth-store.interface';
import {
  MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN,
  type McpOAuthModuleOptions,
  OAUTH_STORE_TOKEN,
} from '../mcp-oauth.module-definition';
import { JWKSService } from './jwks.service';
import { JWTAccessTokenService } from './jwt-access-token.service';

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: 'Bearer';
  expires_in: number;
  scope?: string;
  id_token?: string; // OIDC ID token when openid scope is present
}

export interface TokenValidationResult {
  userId: string;
  clientId: string;
  scope: string;
  resource: string;
  userProfileId: string;
  userData?: unknown;
}

@Injectable()
export class OpaqueTokenService {
  private readonly logger = new Logger(this.constructor.name);

  private readonly ACCESS_TOKEN_BYTES = 64;
  private readonly REFRESH_TOKEN_BYTES = 64;

  public constructor(
    @Inject(MCP_OAUTH_MODULE_OPTIONS_RESOLVED_TOKEN)
    private readonly options: McpOAuthModuleOptions,
    @Inject(OAUTH_STORE_TOKEN) private readonly store: IOAuthStore,
    private readonly jwtAccessTokenService: JWTAccessTokenService,
    private readonly jwksService: JWKSService,
  ) {}

  private generateSecureToken(bytes: number): string {
    return randomBytes(bytes).toString('base64url');
  }

  /**
   * Validates the requested scope against the originally granted scope.
   * According to OAuth 2.0 RFC 6749, the requested scope must not exceed
   * the scope originally granted by the resource owner.
   *
   * @param originalScope - The scope originally granted during authorization
   * @param requestedScope - The scope requested during token refresh (optional)
   * @returns The final scope to use, or null if invalid
   */
  private validateAndDetermineScope(originalScope: string, requestedScope?: string): string | null {
    if (!requestedScope) return originalScope;

    const originalScopes = originalScope.split(' ').filter((s) => s.length > 0);
    const requestedScopes = requestedScope.split(' ').filter((s) => s.length > 0);

    for (const scope of requestedScopes) {
      if (!originalScopes.includes(scope)) {
        this.logger.warn({
          msg: 'Scope validation failed: requested scope not in original grant',
          originalScopes,
          requestedScope: scope,
        });
        return null;
      }
    }

    return requestedScope;
  }

  public async generateTokenPair(
    userId: string,
    clientId: string,
    scope = '',
    resource: string,
    userProfileId: string,
    familyId?: string | null,
    generation = 0,
  ): Promise<TokenPair> {
    let accessToken: string;
    const refreshToken = this.generateSecureToken(this.REFRESH_TOKEN_BYTES);

    const now = Date.now();
    const accessExpiresAt = new Date(now + this.options.accessTokenExpiresIn * 1000);
    const refreshExpiresAt = new Date(now + this.options.refreshTokenExpiresIn * 1000);

    const tokenFamilyId = familyId || typeid('tkfam').toString();

    // Generate access token based on configured format
    if (this.options.accessTokenFormat === 'jwt' && this.jwksService.isJWTEnabled()) {
      // Generate JWT access token
      const tokenId = typeid('jti').toString();
      accessToken = await this.jwtAccessTokenService.generateAccessToken({
        userId,
        clientId,
        scope,
        resource,
        userProfileId,
        expiresIn: this.options.accessTokenExpiresIn,
        tokenId,
        issuer: this.options.serverUrl,
      });

      // Store JWT metadata for revocation tracking
      await this.store.storeAccessToken(tokenId, {
        userId,
        clientId,
        scope,
        resource,
        expiresAt: accessExpiresAt,
        userProfileId,
      });
    } else {
      // Generate opaque access token
      accessToken = this.generateSecureToken(this.ACCESS_TOKEN_BYTES);

      await this.store.storeAccessToken(accessToken, {
        userId,
        clientId,
        scope,
        resource,
        expiresAt: accessExpiresAt,
        userProfileId,
      });
    }

    // Refresh token is always opaque
    await this.store.storeRefreshToken(refreshToken, {
      userId,
      clientId,
      scope,
      resource,
      expiresAt: refreshExpiresAt,
      userProfileId,
      familyId: tokenFamilyId,
      generation,
    });

    this.logger.debug({
      msg: `Generated ${this.options.accessTokenFormat || 'opaque'} access token and refresh token`,
      userId,
      clientId,
      tokenFormat: this.options.accessTokenFormat || 'opaque',
    });

    return {
      access_token: accessToken,
      refresh_token: refreshToken,
      token_type: 'Bearer',
      expires_in: this.options.accessTokenExpiresIn,
      scope,
    };
  }

  public async validateAccessToken(token: string): Promise<TokenValidationResult | null> {
    // Check if token is a JWT
    if (this.options.accessTokenFormat === 'jwt' && this.jwksService.isJWTEnabled()) {
      // Validate JWT access token
      const claims = await this.jwtAccessTokenService.validateAccessToken(
        token,
        this.options.resource,
      );

      if (!claims) {
        this.logger.debug({ msg: 'JWT access token validation failed' });
        return null;
      }

      // Check if token has been revoked (by JTI)
      const metadata = await this.store.getAccessToken(claims.jti);
      if (!metadata) {
        this.logger.debug({ msg: 'JWT access token revoked', jti: claims.jti });
        return null;
      }

      return {
        userId: claims.sub,
        clientId: claims.client_id,
        scope: claims.scope || '',
        resource: claims.resource || this.options.resource,
        userProfileId: claims.user_profile_id || '',
        userData: undefined,
      };
    } else {
      // Validate opaque access token
      const metadata = await this.store.getAccessToken(token);

      if (!metadata) {
        this.logger.debug({ msg: 'Access token not found', tokenPrefix: token.substring(0, 8) });
        return null;
      }

      if (metadata.expiresAt < new Date()) {
        this.logger.debug({
          msg: 'Access token expired',
          tokenPrefix: token.substring(0, 8),
          expiredAt: metadata.expiresAt,
        });
        await this.store.removeAccessToken(token);
        return null;
      }

      return {
        userId: metadata.userId,
        clientId: metadata.clientId,
        scope: metadata.scope,
        resource: metadata.resource,
        userProfileId: metadata.userProfileId,
        userData: metadata.userData,
      };
    }
  }

  public async validateRefreshToken(token: string): Promise<RefreshTokenMetadata | null> {
    const metadata = await this.store.getRefreshToken(token);

    if (!metadata) {
      this.logger.debug({ msg: 'Refresh token not found', tokenPrefix: token.substring(0, 8) });
      return null;
    }

    if (metadata.expiresAt < new Date()) {
      this.logger.debug({
        msg: 'Refresh token expired',
        tokenPrefix: token.substring(0, 8),
        expiredAt: metadata.expiresAt,
      });
      await this.store.removeRefreshToken(token);
      return null;
    }

    return metadata;
  }

  public async refreshAccessToken(
    refreshToken: string,
    clientId: string,
    requestedScope?: string,
  ): Promise<TokenPair | null> {
    if (this.store.isRefreshTokenUsed) {
      const wasUsed = await this.store.isRefreshTokenUsed(refreshToken);
      if (wasUsed) {
        this.logger.error({
          msg: 'SECURITY: Refresh token reuse detected! Revoking entire token family.',
          tokenPrefix: refreshToken.substring(0, 8),
        });

        // Get the token metadata to find the family
        const metadata = await this.store.getRefreshToken(refreshToken);
        if (metadata?.familyId && this.store.revokeTokenFamily) {
          await this.store.revokeTokenFamily(metadata.familyId);
        }

        return null;
      }
    }

    const metadata = await this.validateRefreshToken(refreshToken);
    if (!metadata) return null;

    if (metadata.clientId !== clientId) {
      this.logger.warn({
        msg: 'Client ID mismatch during token refresh',
        expected: metadata.clientId,
        provided: clientId,
      });
      return null;
    }

    // Validate requested scope against originally granted scope
    const finalScope = this.validateAndDetermineScope(metadata.scope, requestedScope);
    if (!finalScope) {
      this.logger.warn({
        msg: 'Invalid scope requested during token refresh',
        originalScope: metadata.scope,
        requestedScope,
      });
      return null;
    }

    if (this.store.markRefreshTokenAsUsed) await this.store.markRefreshTokenAsUsed(refreshToken);

    // Rotate refresh token with same family but incremented generation
    await this.store.removeRefreshToken(refreshToken);
    return this.generateTokenPair(
      metadata.userId,
      metadata.clientId,
      finalScope,
      metadata.resource,
      metadata.userProfileId,
      metadata.familyId,
      (metadata.generation || 0) + 1,
    );
  }

  public async revokeToken(
    token: string,
    tokenType: 'access' | 'refresh' = 'access',
  ): Promise<boolean> {
    try {
      if (tokenType === 'access') {
        await this.store.removeAccessToken(token);
      } else {
        await this.store.removeRefreshToken(token);
      }

      this.logger.debug({
        msg: 'Token revoked',
        tokenType,
        tokenPrefix: token.substring(0, 8),
      });

      return true;
    } catch (error) {
      this.logger.error({
        msg: 'Failed to revoke token',
        tokenType,
        error,
      });
      return false;
    }
  }

  @Cron(CronExpression.EVERY_DAY_AT_2AM)
  private async cleanupExpiredTokens(): Promise<void> {
    if (!this.store.cleanupExpiredTokens) {
      this.logger.debug('Token cleanup not supported by the store implementation');
      return;
    }

    try {
      const deletedCount = await this.store.cleanupExpiredTokens(7);

      if (deletedCount > 0) {
        this.logger.log(`Cleaned up ${deletedCount} expired tokens older than 7 days`);
      } else {
        this.logger.debug('No expired tokens found to cleanup');
      }
    } catch (error) {
      this.logger.error('Failed to cleanup expired tokens', error);
    }
  }
}
