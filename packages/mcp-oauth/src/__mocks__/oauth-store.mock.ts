import type {
  AccessTokenMetadata,
  IOAuthStore,
  RefreshTokenMetadata,
  RevokedTokens,
} from '../interfaces/io-auth-store.interface';
import type { AuthorizationCode, OAuthClient } from '../interfaces/oauth-client.interface';
import type { OAuthSession, OAuthUserProfile } from '../interfaces/oauth-provider.interface';
import type { PassportUser } from '../services/oauth-strategy.service';

export class MockOAuthStore implements IOAuthStore {
  private clients = new Map<string, OAuthClient>();
  private sessions = new Map<string, OAuthSession>();
  private authCodes = new Map<string, AuthorizationCode>();
  private accessTokens = new Map<string, AccessTokenMetadata>();
  private refreshTokens = new Map<string, RefreshTokenMetadata>();
  private userProfiles = new Map<
    string,
    OAuthUserProfile & { profile_id: string; provider: string }
  >();
  private usedRefreshTokens = new Set<string>();

  public generateClientId(_client: OAuthClient): string {
    return `client-${Math.random().toString(36).substr(2, 9)}`;
  }

  public async storeClient(client: OAuthClient): Promise<OAuthClient> {
    this.clients.set(client.client_id, {
      ...client,
      created_at: new Date(),
      updated_at: new Date(),
    });
    // biome-ignore lint/style/noNonNullAssertion: just a mock
    return this.clients.get(client.client_id)!;
  }

  public async getClient(clientId: string): Promise<OAuthClient | undefined> {
    return this.clients.get(clientId);
  }

  public async findClient(clientName: string): Promise<OAuthClient | undefined> {
    for (const client of this.clients.values()) {
      if (client.client_name === clientName) {
        return client;
      }
    }
    return undefined;
  }

  public async storeAuthCode(authCode: AuthorizationCode): Promise<void> {
    this.authCodes.set(authCode.code, authCode);
  }

  public async getAuthCode(code: string): Promise<AuthorizationCode | undefined> {
    return this.authCodes.get(code);
  }

  public async removeAuthCode(code: string): Promise<void> {
    this.authCodes.delete(code);
  }

  public async storeOAuthSession(sessionId: string, session: OAuthSession): Promise<void> {
    this.sessions.set(sessionId, session);
  }

  public async getOAuthSession(sessionId: string): Promise<OAuthSession | undefined> {
    return this.sessions.get(sessionId);
  }

  public async removeOAuthSession(sessionId: string): Promise<void> {
    this.sessions.delete(sessionId);
  }

  public async storeAccessToken(token: string, metadata: AccessTokenMetadata): Promise<void> {
    this.accessTokens.set(token, metadata);
  }

  public async getAccessToken(token: string): Promise<AccessTokenMetadata | undefined> {
    return this.accessTokens.get(token);
  }

  public async removeAccessToken(token: string): Promise<void> {
    this.accessTokens.delete(token);
  }

  public async storeRefreshToken(token: string, metadata: RefreshTokenMetadata): Promise<void> {
    this.refreshTokens.set(token, metadata);
  }

  public async getRefreshToken(token: string): Promise<RefreshTokenMetadata | undefined> {
    return this.refreshTokens.get(token);
  }

  public async removeRefreshToken(token: string): Promise<void> {
    this.refreshTokens.delete(token);
  }

  public async revokeTokenFamily(familyId: string): Promise<void> {
    for (const [token, metadata] of this.refreshTokens.entries()) {
      if (metadata.familyId === familyId) {
        this.refreshTokens.delete(token);
      }
    }
  }

  public async revokeAllTokensForUserProfile(userProfileId: string): Promise<RevokedTokens> {
    const clientIds = new Set<string>();
    let tokenCount = 0;

    for (const tokenStore of [this.accessTokens, this.refreshTokens]) {
      for (const [token, metadata] of [...tokenStore.entries()]) {
        if (metadata.userProfileId === userProfileId) {
          tokenStore.delete(token);
          clientIds.add(metadata.clientId);
          tokenCount += 1;
        }
      }
    }

    return { tokenCount, clientIds: [...clientIds] };
  }

  public async markRefreshTokenAsUsed(token: string): Promise<void> {
    this.usedRefreshTokens.add(token);
  }

  public async isRefreshTokenUsed(token: string): Promise<boolean> {
    return this.usedRefreshTokens.has(token);
  }

  public async upsertUserProfile(user: PassportUser): Promise<string> {
    const profileId = `profile-${user.profile.id}-${user.provider}`;

    const profile = {
      profile_id: profileId,
      provider: user.provider,
      id: user.profile.id,
      username: user.profile.username,
      email: user.profile.email,
      displayName: user.profile.displayName,
      avatarUrl: user.profile.avatarUrl,
      raw: user,
    };

    this.userProfiles.set(profileId, profile);
    return profileId;
  }

  public async getUserProfileById(
    profileId: string,
  ): Promise<(OAuthUserProfile & { profile_id: string; provider: string }) | undefined> {
    return this.userProfiles.get(profileId);
  }

  public async cleanupExpiredTokens(olderThanDays: number = 30): Promise<number> {
    const cutoffTime = new Date(Date.now() - olderThanDays * 24 * 60 * 60 * 1000);
    let cleanedCount = 0;

    for (const [token, metadata] of this.accessTokens.entries()) {
      if (metadata.expiresAt < cutoffTime) {
        this.accessTokens.delete(token);
        cleanedCount++;
      }
    }

    for (const [token, metadata] of this.refreshTokens.entries()) {
      if (metadata.expiresAt < cutoffTime) {
        this.refreshTokens.delete(token);
        cleanedCount++;
      }
    }

    return cleanedCount;
  }

  public clear(): void {
    this.clients.clear();
    this.sessions.clear();
    this.authCodes.clear();
    this.accessTokens.clear();
    this.refreshTokens.clear();
    this.userProfiles.clear();
    this.usedRefreshTokens.clear();
  }

  public clearDynamicData(): void {
    // Clear only tokens, sessions, and auth codes - preserve registered clients
    this.sessions.clear();
    this.authCodes.clear();
    this.accessTokens.clear();
    this.refreshTokens.clear();
    this.userProfiles.clear();
    this.usedRefreshTokens.clear();
  }

  public getStoredData() {
    return {
      clients: Array.from(this.clients.values()),
      sessions: Array.from(this.sessions.values()),
      authCodes: Array.from(this.authCodes.values()),
      accessTokens: Array.from(this.accessTokens.values()),
      refreshTokens: Array.from(this.refreshTokens.values()),
      userProfiles: Array.from(this.userProfiles.values()),
    };
  }
}
