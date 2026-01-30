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
import { typeid } from 'typeid-js';
import { PrismaService } from '../prisma/prisma.service';
import {
  convertAuthCodeToPrisma,
  convertOAuthClientToPrisma,
  convertPrismaToAuthCode,
  convertPrismaToOAuthClient,
  convertPrismaToSession,
  convertSessionToPrisma,
} from '../utils/case-converter';

export class McpOAuthStore implements IOAuthStore {
  private readonly logger = new Logger(this.constructor.name);

  private readonly ACCESS_TOKEN_CACHE_PREFIX = 'access_token:';
  private readonly REFRESH_TOKEN_CACHE_PREFIX = 'refresh_token:';

  public constructor(
    private readonly prisma: PrismaService,
    private readonly encryptionService: IEncryptionService,
    private readonly cacheManager: Cache,
  ) {}

  public async storeClient(client: OAuthClient): Promise<OAuthClient> {
    const saved = await this.prisma.oAuthClient.create({
      data: convertOAuthClientToPrisma(client),
    });

    return convertPrismaToOAuthClient(saved);
  }

  public async getClient(client_id: string): Promise<OAuthClient | undefined> {
    const client = await this.prisma.oAuthClient.findUnique({
      where: { clientId: client_id },
    });

    if (!client) return undefined;

    return convertPrismaToOAuthClient(client);
  }

  public async findClient(client_name: string): Promise<OAuthClient | undefined> {
    const client = await this.prisma.oAuthClient.findFirst({
      where: { clientName: client_name },
    });

    if (!client) return undefined;

    return convertPrismaToOAuthClient(client);
  }

  public generateClientId(client: OAuthClient): string {
    const normalizedName = client.client_name.toLowerCase().replace(/[^a-z0-9]/g, '');
    return typeid(normalizedName).toString();
  }

  public async storeAuthCode(code: AuthorizationCode): Promise<void> {
    await this.prisma.authorizationCode.create({
      data: convertAuthCodeToPrisma(code),
    });
  }

  public async getAuthCode(code: string): Promise<AuthorizationCode | undefined> {
    const authCode = await this.prisma.authorizationCode.findUnique({
      where: { code },
    });

    if (!authCode) return undefined;
    if (authCode.expiresAt < new Date()) {
      await this.removeAuthCode(code);
      return undefined;
    }

    return convertPrismaToAuthCode(authCode);
  }

  public async removeAuthCode(code: string): Promise<void> {
    await this.prisma.authorizationCode
      .delete({
        where: { code },
      })
      .catch((error) => {
        this.logger.warn(`Failed to remove auth code: ${error.message}`);
      });
  }

  public async storeOAuthSession(sessionId: string, session: OAuthSession): Promise<void> {
    const prismaData = convertSessionToPrisma(session);

    await this.prisma.oAuthSession.create({
      data: {
        ...prismaData,
        sessionId,
      },
    });
  }

  public async getOAuthSession(sessionId: string): Promise<OAuthSession | undefined> {
    const session = await this.prisma.oAuthSession.findUnique({
      where: { sessionId },
    });

    if (!session) return undefined;
    if (session.expiresAt < new Date()) {
      await this.removeOAuthSession(sessionId);
      return undefined;
    }

    return convertPrismaToSession(session);
  }

  public async removeOAuthSession(sessionId: string): Promise<void> {
    await this.prisma.oAuthSession
      .delete({
        where: { sessionId },
      })
      .catch((error) => {
        this.logger.warn(`Failed to remove OAuth session: ${error.message}`);
      });
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

    const saved = await this.prisma.userProfile.upsert({
      where: {
        provider_providerUserId: {
          provider,
          providerUserId: profile.id,
        },
      },
      update: mappedProfile,
      create: mappedProfile,
    });

    return saved.id;
  }

  public async getUserProfileById(
    profileId: string,
  ): Promise<(OAuthUserProfile & { profile_id: string; provider: string }) | undefined> {
    const profile = await this.prisma.userProfile.findUnique({
      where: { id: profileId },
    });

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

    await this.prisma.token.create({
      data: {
        token,
        type: 'ACCESS',
        expiresAt: metadata.expiresAt,
        userId: metadata.userId,
        clientId: metadata.clientId,
        scope: metadata.scope,
        resource: metadata.resource,
        userProfileId: metadata.userProfileId,
      },
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

    const metadata = await this.prisma.token.findUnique({
      where: { token },
      include: {
        userProfile: true,
      },
    });
    if (!metadata) return undefined;
    if (metadata.expiresAt < new Date()) {
      await this.removeAccessToken(token);
      return undefined;
    }

    const result = {
      ...metadata,
      userData: metadata.userProfile?.raw,
    };

    await this.cacheAccessTokenMetadata(token, result);

    return result;
  }

  public async removeAccessToken(token: string): Promise<void> {
    await this.prisma.token.delete({
      where: { token },
    });

    await this.removeCachedAccessToken(token);
  }

  public async storeRefreshToken(token: string, metadata: RefreshTokenMetadata): Promise<void> {
    const profile = await this.getUserProfileById(metadata.userProfileId);
    if (!profile) throw new Error('User profile not found');

    await this.prisma.token.create({
      data: {
        token,
        type: 'REFRESH',
        expiresAt: metadata.expiresAt,
        userId: metadata.userId,
        clientId: metadata.clientId,
        scope: metadata.scope,
        resource: metadata.resource,
        userProfileId: metadata.userProfileId,
        familyId: metadata.familyId,
        generation: metadata.generation,
      },
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

    const metadata = await this.prisma.token.findUnique({
      where: { token },
    });

    if (!metadata) return undefined;
    if (metadata.expiresAt < new Date()) {
      await this.removeRefreshToken(token);
      return undefined;
    }

    await this.cacheRefreshTokenMetadata(token, metadata);

    return metadata;
  }

  public async removeRefreshToken(token: string): Promise<void> {
    await this.prisma.token.delete({
      where: { token },
    });

    await this.removeCachedRefreshToken(token);
  }

  public async revokeTokenFamily(familyId: string): Promise<void> {
    const tokensInFamily = await this.prisma.token.findMany({
      where: { familyId },
      select: { token: true, type: true },
    });

    await this.prisma.token.deleteMany({
      where: { familyId },
    });

    for (const tokenData of tokensInFamily) {
      if (tokenData.type === 'ACCESS') {
        await this.removeCachedAccessToken(tokenData.token);
      } else if (tokenData.type === 'REFRESH') {
        await this.removeCachedRefreshToken(tokenData.token);
      }
    }
  }

  public async markRefreshTokenAsUsed(token: string): Promise<void> {
    await this.prisma.token.update({
      where: { token },
      data: { usedAt: new Date() },
    });

    await this.removeCachedRefreshToken(token);
  }

  public async isRefreshTokenUsed(token: string): Promise<boolean> {
    const metadata = await this.prisma.token.findUnique({
      where: { token },
    });

    return !!metadata?.usedAt;
  }

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

    if (ttl > 0) await this.cacheManager.set(cacheKey, metadata, ttl);
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

    this.logger.debug(`Cleaning up tokens expired before ${cutoffDate.toISOString()}`);

    const deletedTokens = await this.prisma.token.deleteMany({
      where: {
        expiresAt: {
          lt: cutoffDate,
        },
      },
    });

    const deletedAuthCodes = await this.prisma.authorizationCode.deleteMany({
      where: {
        expiresAt: {
          lt: cutoffDate,
        },
      },
    });

    const deletedSessions = await this.prisma.oAuthSession.deleteMany({
      where: {
        expiresAt: {
          lt: cutoffDate,
        },
      },
    });

    const totalDeleted = deletedTokens.count + deletedAuthCodes.count + deletedSessions.count;

    if (totalDeleted > 0) {
      this.logger.log(
        `Cleanup completed: ${deletedTokens.count} tokens, ${deletedAuthCodes.count} auth codes, ${deletedSessions.count} sessions deleted`,
      );
    }

    return totalDeleted;
  }
}
