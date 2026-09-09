import { PassportUser } from '../services/oauth-strategy.service';
import { AuthorizationCode, OAuthClient } from './oauth-client.interface';
import { OAuthSession, OAuthUserProfile } from './oauth-provider.interface';

export interface AccessTokenMetadata {
  userId: string;
  clientId: string;
  scope: string;
  resource: string;
  expiresAt: Date;
  userProfileId: string;
  userData?: unknown;
}

export interface RefreshTokenMetadata {
  userId: string;
  clientId: string;
  scope: string;
  resource: string;
  expiresAt: Date;
  userProfileId: string;
  familyId?: string | null;
  generation?: number | null;
}

/** What a profile-wide revocation swept away, so callers can log the blast radius. */
export interface RevokedTokens {
  tokenCount: number;
  clientIds: string[];
}

export interface IOAuthStore {
  // Client management
  storeClient(client: OAuthClient): Promise<OAuthClient>;
  getClient(client_id: string): Promise<OAuthClient | undefined>;
  findClient(client_name: string): Promise<OAuthClient | undefined>;
  generateClientId(client: OAuthClient): string;

  // Authorization code management
  storeAuthCode(code: AuthorizationCode): Promise<void>;
  getAuthCode(code: string): Promise<AuthorizationCode | undefined>;
  removeAuthCode(code: string): Promise<void>;

  // OAuth session management
  storeOAuthSession(sessionId: string, session: OAuthSession): Promise<void>;
  getOAuthSession(sessionId: string): Promise<OAuthSession | undefined>;
  removeOAuthSession(sessionId: string): Promise<void>;

  // Token management (for opaque tokens)
  storeAccessToken(token: string, metadata: AccessTokenMetadata): Promise<void>;
  getAccessToken(token: string): Promise<AccessTokenMetadata | undefined>;
  removeAccessToken(token: string): Promise<void>;

  storeRefreshToken(token: string, metadata: RefreshTokenMetadata): Promise<void>;
  getRefreshToken(token: string): Promise<RefreshTokenMetadata | undefined>;
  removeRefreshToken(token: string): Promise<void>;

  // Refresh token family management for reuse detection
  revokeTokenFamily?(familyId: string): Promise<void>;
  markRefreshTokenAsUsed?(token: string): Promise<void>;
  isRefreshTokenUsed?(token: string): Promise<boolean>;

  /**
   * Delete every MCP access/refresh token for a user profile.
   * Used when the upstream credential (e.g. Microsoft refresh token) is permanently dead.
   *
   * One profile is normally shared by several registered clients, so this reports which ones
   * it disconnected rather than returning nothing.
   */
  revokeAllTokensForUserProfile?(userProfileId: string): Promise<RevokedTokens>;

  // User profile management
  /**
   * Upsert a user profile from an OAuth provider and return a stable profile_id.
   * The profile_id should be stable across logins for the same provider+user.
   */
  upsertUserProfile(user: PassportUser): Promise<string>;

  getUserProfileById(
    profileId: string,
  ): Promise<(OAuthUserProfile & { profile_id: string; provider: string }) | undefined>;

  // Token cleanup
  cleanupExpiredTokens?(olderThanDays: number): Promise<number>;
}
