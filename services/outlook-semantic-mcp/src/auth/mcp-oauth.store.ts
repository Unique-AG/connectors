import assert from 'node:assert';
import {
  AccessTokenMetadata,
  AuthorizationCode,
  type IEncryptionService,
  IOAuthStore,
  OAuthClient,
  OAuthSession,
  OAuthUserProfile,
  PassportUser,
  RefreshTokenMetadata,
} from '@unique-ag/mcp-oauth';
import { Logger } from '@nestjs/common';
import { Cache } from 'cache-manager';
import { eq, lt } from 'drizzle-orm';
import { typeid } from 'typeid-js';
import { DrizzleDatabase } from '../drizzle/drizzle.module';
import {
  authorizationCodes,
  oauthClients,
  oauthSessions,
  tokens,
  userProfiles,
} from '../drizzle/schema';
import {
  fromDrizzleAuthCodeRow,
  fromDrizzleOAuthClientRow,
  fromDrizzleSessionRow,
  toDrizzleAuthCodeInsert,
  toDrizzleOAuthClientInsert,
  toDrizzleSessionInsert,
} from '../utils/case-converter';

export class McpOAuthStore implements IOAuthStore {
  private readonly logger = new Logger(this.constructor.name);

  // Cache key prefixes
  private readonly ACCESS_TOKEN_CACHE_PREFIX = 'access_token:';
  private readonly REFRESH_TOKEN_CACHE_PREFIX = 'refresh_token:';

  public constructor(
    private readonly drizzle: DrizzleDatabase,
    private readonly encryptionService: IEncryptionService,
    private readonly cacheManager: Cache,
  ) {}

  public async storeClient(client: OAuthClient): Promise<OAuthClient> {
    const saved = await this.drizzle
      .insert(oauthClients)
      .values(toDrizzleOAuthClientInsert(client))
      .returning();
    const savedClient = saved.at(0);
    assert.ok(savedClient, "Save didn't return a client");

    return fromDrizzleOAuthClientRow(savedClient);
  }

  public async getClient(client_id: string): Promise<OAuthClient | undefined> {
    const [client] = await this.drizzle
      .select()
      .from(oauthClients)
      .where(eq(oauthClients.clientId, client_id));
    if (!client) return undefined;
    return fromDrizzleOAuthClientRow(client);
  }

  public async findClient(client_name: string): Promise<OAuthClient | undefined> {
    const [client] = await this.drizzle
      .select()
      .from(oauthClients)
      .where(eq(oauthClients.clientName, client_name));
    if (!client) return undefined;
    return fromDrizzleOAuthClientRow(client);
  }

  public generateClientId(client: OAuthClient): string {
    const normalizedName = client.client_name.toLowerCase().replace(/[^a-z0-9]/g, '');
    // TODO: We need to discuss if we want to add the normalizedName as a clientId prefix.
    return typeid(normalizedName).toString();
  }

  public async storeAuthCode(code: AuthorizationCode): Promise<void> {
    await this.drizzle.insert(authorizationCodes).values(toDrizzleAuthCodeInsert(code));
  }

  public async getAuthCode(code: string): Promise<AuthorizationCode | undefined> {
    const [authCode] = await this.drizzle
      .select()
      .from(authorizationCodes)
      .where(eq(authorizationCodes.code, code));
    if (!authCode) return undefined;
    if (authCode.expiresAt < new Date()) {
      await this.removeAuthCode(code);
      return undefined;
    }
    return fromDrizzleAuthCodeRow(authCode);
  }

  public async removeAuthCode(code: string): Promise<void> {
    try {
      await this.drizzle.delete(authorizationCodes).where(eq(authorizationCodes.code, code));
    } catch (error) {
      this.logger.warn(
        {
          message: 'Failed to delete expired authorization code from database',
          operation: 'cleanup_auth_code',
        },
        error,
      );
    }
  }

  public async storeOAuthSession(sessionId: string, session: OAuthSession): Promise<void> {
    const payload = toDrizzleSessionInsert(session);
    await this.drizzle.insert(oauthSessions).values({ ...payload, sessionId });
  }

  public async getOAuthSession(sessionId: string): Promise<OAuthSession | undefined> {
    const [session] = await this.drizzle
      .select()
      .from(oauthSessions)
      .where(eq(oauthSessions.sessionId, sessionId));
    if (!session) return undefined;
    if (session.expiresAt && session.expiresAt < new Date()) {
      await this.removeOAuthSession(sessionId);
      return undefined;
    }
    return fromDrizzleSessionRow(session);
  }

  public async removeOAuthSession(sessionId: string): Promise<void> {
    try {
      await this.drizzle.delete(oauthSessions).where(eq(oauthSessions.sessionId, sessionId));
    } catch (error) {
      this.logger.warn(
        {
          message: 'Failed to delete expired OAuth session from database',
          operation: 'cleanup_oauth_session',
        },
        error,
      );
    }
  }

  public async upsertUserProfile(user: PassportUser): Promise<string> {
    const { profile, accessToken, refreshToken, provider } = user;

    const encryptedAccessToken = this.encryptionService.encryptToString(accessToken);
    const encryptedRefreshToken = this.encryptionService.encryptToString(refreshToken);

    const mappedProfile = {
      provider,
      providerUserId: profile.id,
      username: profile.username,
      email: profile.email,
      displayName: profile.displayName,
      avatarUrl: profile.avatarUrl,
      raw: profile.raw,
      accessToken: encryptedAccessToken,
      refreshToken: encryptedRefreshToken,
    };

    const [saved] = await this.drizzle
      .insert(userProfiles)
      .values(mappedProfile)
      .onConflictDoUpdate({
        target: [userProfiles.provider, userProfiles.providerUserId],
        set: mappedProfile,
      })
      .returning({ id: userProfiles.id });
    if (!saved) throw new Error('Failed to upsert user profile');

    return saved.id;
  }

  public async getUserProfileById(
    profileId: string,
  ): Promise<(OAuthUserProfile & { profile_id: string; provider: string }) | undefined> {
    const [profile] = await this.drizzle
      .select()
      .from(userProfiles)
      .where(eq(userProfiles.id, profileId));

    if (!profile) return undefined;

    return {
      profile_id: profile.id,
      provider: profile.provider,
      id: profile.providerUserId,
      username: profile.username,
      email: profile.email || undefined,
      displayName: profile.displayName || undefined,
      avatarUrl: profile.avatarUrl || undefined,
      raw: profile.raw || undefined,
    };
  }

  public async storeAccessToken(token: string, metadata: AccessTokenMetadata): Promise<void> {
    const profile = await this.getUserProfileById(metadata.userProfileId);
    if (!profile) throw new Error('User profile not found');

    await this.drizzle.insert(tokens).values({
      token,
      type: 'ACCESS',
      expiresAt: metadata.expiresAt,
      userId: metadata.userId,
      clientId: metadata.clientId,
      scope: metadata.scope,
      resource: metadata.resource,
      userProfileId: metadata.userProfileId,
    });

    await this.cacheAccessTokenMetadata(token, metadata);
  }

  public async getAccessToken(token: string): Promise<AccessTokenMetadata | undefined> {
    const cacheKey = this.getAccessTokenCacheKey(token);
    const cached = await this.cacheManager.get<AccessTokenMetadata>(cacheKey);

    if (cached) {
      if (cached.expiresAt < new Date()) {
        await this.removeAccessToken(token);
        return undefined;
      }
      return cached;
    }

    const metadata = await this.drizzle
      .select({
        token: tokens.token,
        type: tokens.type,
        expiresAt: tokens.expiresAt,
        userId: tokens.userId,
        clientId: tokens.clientId,
        scope: tokens.scope,
        resource: tokens.resource,
        userProfileId: tokens.userProfileId,
        userData: userProfiles.raw,
      })
      .from(tokens)
      .leftJoin(userProfiles, eq(tokens.userProfileId, userProfiles.id))
      .where(eq(tokens.token, token))
      .then((rows) => rows[0]);
    if (!metadata) return undefined;
    if (metadata.expiresAt < new Date()) {
      await this.removeAccessToken(token);
      return undefined;
    }

    await this.cacheAccessTokenMetadata(token, metadata as unknown as AccessTokenMetadata);
    return metadata as unknown as AccessTokenMetadata;
  }

  public async removeAccessToken(token: string): Promise<void> {
    await this.drizzle.delete(tokens).where(eq(tokens.token, token));

    await this.removeCachedAccessToken(token);
  }

  public async storeRefreshToken(token: string, metadata: RefreshTokenMetadata): Promise<void> {
    const profile = await this.getUserProfileById(metadata.userProfileId);
    if (!profile) throw new Error('User profile not found');

    await this.drizzle.insert(tokens).values({
      token,
      type: 'REFRESH',
      expiresAt: metadata.expiresAt,
      userId: metadata.userId,
      clientId: metadata.clientId,
      scope: metadata.scope,
      resource: metadata.resource,
      userProfileId: metadata.userProfileId,
      familyId: metadata.familyId ?? undefined,
      generation: metadata.generation ?? undefined,
    });

    await this.cacheRefreshTokenMetadata(token, metadata);
  }

  public async getRefreshToken(token: string): Promise<RefreshTokenMetadata | undefined> {
    const cacheKey = this.getRefreshTokenCacheKey(token);
    const cached = await this.cacheManager.get<RefreshTokenMetadata>(cacheKey);

    if (cached) {
      if (cached.expiresAt < new Date()) {
        await this.removeRefreshToken(token);
        return undefined;
      }
      return cached;
    }

    const metadata = await this.drizzle
      .select({
        token: tokens.token,
        type: tokens.type,
        expiresAt: tokens.expiresAt,
        userId: tokens.userId,
        clientId: tokens.clientId,
        scope: tokens.scope,
        resource: tokens.resource,
        userProfileId: tokens.userProfileId,
        familyId: tokens.familyId,
        generation: tokens.generation,
      })
      .from(tokens)
      .where(eq(tokens.token, token))
      .then((rows) => rows[0]);

    if (!metadata) return undefined;
    if (metadata.expiresAt < new Date()) {
      await this.removeRefreshToken(token);
      return undefined;
    }

    await this.cacheRefreshTokenMetadata(token, metadata);

    return metadata;
  }

  public async removeRefreshToken(token: string): Promise<void> {
    await this.drizzle.delete(tokens).where(eq(tokens.token, token));

    await this.removeCachedRefreshToken(token);
  }

  public async revokeTokenFamily(familyId: string): Promise<void> {
    // First, get all tokens in the family from database to remove from cache
    const tokensInFamily = await this.drizzle
      .select({ token: tokens.token, type: tokens.type })
      .from(tokens)
      .where(eq(tokens.familyId, familyId));

    await this.drizzle.delete(tokens).where(eq(tokens.familyId, familyId));

    // Remove each token from cache
    for (const tokenData of tokensInFamily) {
      if (tokenData.type === 'ACCESS') {
        await this.removeCachedAccessToken(tokenData.token);
      } else if (tokenData.type === 'REFRESH') {
        await this.removeCachedRefreshToken(tokenData.token);
      }
    }
  }

  public async markRefreshTokenAsUsed(token: string): Promise<void> {
    await this.drizzle.update(tokens).set({ usedAt: new Date() }).where(eq(tokens.token, token));

    await this.removeCachedRefreshToken(token);
  }

  public async isRefreshTokenUsed(token: string): Promise<boolean> {
    // Always check DB, not cache.
    const [metadata] = await this.drizzle
      .select({ usedAt: tokens.usedAt })
      .from(tokens)
      .where(eq(tokens.token, token));

    return !!metadata?.usedAt;
  }

  // Cache helper methods
  private getAccessTokenCacheKey(token: string): string {
    return `${this.ACCESS_TOKEN_CACHE_PREFIX}${token}`;
  }

  private getRefreshTokenCacheKey(token: string): string {
    return `${this.REFRESH_TOKEN_CACHE_PREFIX}${token}`;
  }

  private async cacheAccessTokenMetadata(
    token: string,
    metadata: AccessTokenMetadata,
  ): Promise<void> {
    const cacheKey = this.getAccessTokenCacheKey(token);
    const ttl = Math.max(0, Math.floor((metadata.expiresAt.getTime() - Date.now()) / 1000));

    if (ttl > 0) await this.cacheManager.set(cacheKey, metadata, ttl);
  }

  private async cacheRefreshTokenMetadata(
    token: string,
    metadata: RefreshTokenMetadata,
  ): Promise<void> {
    const cacheKey = this.getRefreshTokenCacheKey(token);
    const ttl = Math.max(0, Math.floor((metadata.expiresAt.getTime() - Date.now()) / 1000));

    if (ttl > 0) {
      await this.cacheManager.set(cacheKey, metadata, ttl);
    }
  }

  private async removeCachedAccessToken(token: string): Promise<void> {
    const cacheKey = this.getAccessTokenCacheKey(token);
    await this.cacheManager.del(cacheKey);
  }

  private async removeCachedRefreshToken(token: string): Promise<void> {
    const cacheKey = this.getRefreshTokenCacheKey(token);
    await this.cacheManager.del(cacheKey);
  }

  public async cleanupExpiredTokens(olderThanDays: number): Promise<number> {
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - olderThanDays);

    this.logger.debug(
      {
        cutoffDate: cutoffDate.toISOString(),
        olderThanDays,
        operation: 'cleanup_expired_tokens',
      },
      'Beginning cleanup of expired tokens and sessions from database',
    );

    const deletedTokens = await this.drizzle
      .delete(tokens)
      .where(lt(tokens.expiresAt, cutoffDate))
      .returning({ id: tokens.id });

    const deletedAuthCodes = await this.drizzle
      .delete(authorizationCodes)
      .where(lt(authorizationCodes.expiresAt, cutoffDate))
      .returning({ id: authorizationCodes.id });

    const deletedSessions = await this.drizzle
      .delete(oauthSessions)
      .where(lt(oauthSessions.expiresAt, cutoffDate))
      .returning({ id: oauthSessions.id });

    const totalDeleted = deletedTokens.length + deletedAuthCodes.length + deletedSessions.length;

    return totalDeleted;
  }
}
