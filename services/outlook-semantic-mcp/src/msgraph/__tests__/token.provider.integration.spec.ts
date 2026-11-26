/** biome-ignore-all lint/suspicious/noExplicitAny: Dispatcher and fetch response stand-ins */
import assert from 'node:assert';
import path from 'node:path';
import { UpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import type { Pool } from 'pg';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockEncryptionService } from '../../__mocks__';
import { createPostgresPool, stopPostgres } from '../../__mocks__/stop-postgres';
import type { DrizzleDatabase } from '../../db/drizzle.module';
import * as schema from '../../db/schema';

vi.mock('undici', async (importOriginal) => ({
  ...(await importOriginal<typeof import('undici')>()),
  fetch: vi.fn(),
}));

import { fetch } from 'undici';
import { TokenProvider, TokenRefreshCoolingDownError } from '../token.provider';

const CONTAINER_STARTUP_TIMEOUT_MS = 120_000;
const mockFetch = vi.mocked(fetch);
const encryption = new MockEncryptionService();

const tokensResponse = (accessToken: string, refreshToken?: string) =>
  ({
    ok: true,
    json: async () => ({ access_token: accessToken, refresh_token: refreshToken }),
  }) as any;

const oauthErrorResponse = (status: number, error: string) =>
  ({
    ok: false,
    status,
    statusText: 'Failed',
    headers: new Headers(),
    text: async () => JSON.stringify({ error }),
  }) as any;

const connectTimeout = () =>
  Object.assign(new TypeError('fetch failed'), { cause: { code: 'UND_ERR_CONNECT_TIMEOUT' } });

describe('TokenProvider against Postgres', () => {
  let container: StartedPostgreSqlContainer;
  let pool: Pool;
  let db: DrizzleDatabase;
  let userProfileId: string;
  let onPermanentAuthFailure: ReturnType<typeof vi.fn<(userProfileId: string) => Promise<void>>>;

  beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start();
    pool = createPostgresPool(container.getConnectionUri());
    db = drizzle({ client: pool, casing: 'snake_case', schema });
    await migrate(db, { migrationsFolder: path.resolve(__dirname, '../../../drizzle') });
  }, CONTAINER_STARTUP_TIMEOUT_MS);

  afterAll(async () => {
    await stopPostgres(pool, container);
  });

  beforeEach(async () => {
    mockFetch.mockReset();
    onPermanentAuthFailure = vi.fn<(userProfileId: string) => Promise<void>>().mockResolvedValue();
    await db.delete(schema.userProfiles);
    const [user] = await db
      .insert(schema.userProfiles)
      .values({
        provider: 'microsoft',
        providerUserId: 'alice',
        username: 'alice',
        email: 'alice@contoso.example',
        accessToken: encryption.encryptToString('old-access-token'),
        refreshToken: encryption.encryptToString('old-refresh-token'),
      })
      .returning({ id: schema.userProfiles.id });
    assert.ok(user);
    userProfileId = user.id;
  });

  // Each instance stands for a Graph client, possibly on another pod; they share only the database.
  const createProvider = () =>
    new TokenProvider(
      {
        userProfileId,
        clientId: 'client-id',
        clientSecret: 'client-secret',
        signInTenantId: 'common',
        allowedTenantIds: [],
        scopes: ['https://graph.microsoft.com/.default'],
      },
      {
        drizzle: db,
        encryptionService: encryption as any,
        dispatcher: {} as any,
        onPermanentAuthFailure,
      },
    );

  async function storedProfile() {
    const [row] = await db
      .select()
      .from(schema.userProfiles)
      .where(eq(schema.userProfiles.id, userProfileId));
    assert.ok(row);
    return {
      ...row,
      accessToken: row.accessToken && encryption.decryptFromString(row.accessToken).toString(),
      refreshToken: row.refreshToken && encryption.decryptFromString(row.refreshToken).toString(),
    };
  }

  // A sign-in that lands while Entra ID is still answering the refresh of the old grant.
  const signInDuringRefresh = async () => {
    await db
      .update(schema.userProfiles)
      .set({
        accessToken: encryption.encryptToString('new-access-token'),
        refreshToken: encryption.encryptToString('new-refresh-token'),
        ...schema.CLEARED_TOKEN_REFRESH_BACKOFF,
      })
      .where(eq(schema.userProfiles.id, userProfileId));
  };

  it('stores the refreshed tokens and ends a previous backoff', async () => {
    await db
      .update(schema.userProfiles)
      .set({
        tokenRefreshFailedAt: new Date(Date.now() - 10 * 60_000),
        tokenRefreshFailureCount: 2,
        tokenRefreshFailureCode: 'http_503',
        tokenRefreshRetryAt: new Date(Date.now() - 60_000),
      })
      .where(eq(schema.userProfiles.id, userProfileId));
    mockFetch.mockResolvedValue(tokensResponse('fresh-access-token', 'fresh-refresh-token'));

    await expect(createProvider().refreshAccessToken(userProfileId)).resolves.toBe(
      'fresh-access-token',
    );

    expect(await storedProfile()).toMatchObject({
      accessToken: 'fresh-access-token',
      refreshToken: 'fresh-refresh-token',
      tokenRefreshFailedAt: null,
      tokenRefreshFailureCount: 0,
      tokenRefreshFailureCode: null,
      tokenRefreshRetryAt: null,
    });
  });

  it('backs off on every pod after a transient failure', async () => {
    mockFetch.mockRejectedValue(connectTimeout());

    await expect(createProvider().refreshAccessToken(userProfileId)).rejects.toThrow(
      'Token refresh failed',
    );

    const stored = await storedProfile();
    expect(stored).toMatchObject({
      accessToken: 'old-access-token',
      refreshToken: 'old-refresh-token',
      tokenRefreshFailureCount: 1,
      tokenRefreshFailureCode: 'network_UND_ERR_CONNECT_TIMEOUT',
    });
    // Measured between the stored timestamps, so database and scheduling delay cannot skew it.
    expect(
      (stored.tokenRefreshRetryAt?.getTime() ?? 0) - (stored.tokenRefreshFailedAt?.getTime() ?? 0),
    ).toBe(60_000);

    await expect(createProvider().refreshAccessToken(userProfileId)).rejects.toBeInstanceOf(
      TokenRefreshCoolingDownError,
    );
    expect(mockFetch).toHaveBeenCalledOnce();
  });

  it('reuses the token another pod already stored', async () => {
    await expect(
      createProvider().refreshAccessToken(userProfileId, 'expired-access-token'),
    ).resolves.toBe('old-access-token');
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it('clears the tokens and revokes the MCP session when Entra ID rejects the grant', async () => {
    mockFetch.mockResolvedValue(oauthErrorResponse(400, 'invalid_grant'));

    await expect(createProvider().refreshAccessToken(userProfileId)).rejects.toBeInstanceOf(
      UpstreamCredentialRevokedError,
    );

    expect(await storedProfile()).toMatchObject({ accessToken: null, refreshToken: null });
    expect(onPermanentAuthFailure).toHaveBeenCalledWith(userProfileId);
  });

  describe('a user signed in without offline_access', () => {
    beforeEach(async () => {
      await db
        .update(schema.userProfiles)
        .set({ refreshToken: null })
        .where(eq(schema.userProfiles.id, userProfileId));
    });

    afterEach(() => {
      vi.restoreAllMocks();
    });

    it('skips the token endpoint, clears the tokens and revokes the MCP session', async () => {
      await expect(createProvider().refreshAccessToken(userProfileId)).rejects.toBeInstanceOf(
        UpstreamCredentialRevokedError,
      );

      expect(mockFetch).not.toHaveBeenCalled();
      expect(await storedProfile()).toMatchObject({ accessToken: null, refreshToken: null });
      expect(onPermanentAuthFailure).toHaveBeenCalledWith(userProfileId);
    });

    it('asks for a new sign-in again when a concurrent request already revoked the grant', async () => {
      await expect(createProvider().refreshAccessToken(userProfileId)).rejects.toBeInstanceOf(
        UpstreamCredentialRevokedError,
      );

      await expect(createProvider().refreshAccessToken(userProfileId)).rejects.toBeInstanceOf(
        UpstreamCredentialRevokedError,
      );
      expect(onPermanentAuthFailure).toHaveBeenCalledTimes(1);
    });

    it('keeps a new sign-in that replaced the expired one', async () => {
      const provider = createProvider();
      const stale = await db.query.userProfiles.findFirst({
        where: eq(schema.userProfiles.id, userProfileId),
      });
      await db
        .update(schema.userProfiles)
        .set({ accessToken: encryption.encryptToString('new-access-token') })
        .where(eq(schema.userProfiles.id, userProfileId));
      // The provider read the profile just before the new sign-in landed. No Microsoft call sits
      // between that read and the revoke to hook into, so the read itself returns the stale row.
      vi.spyOn(db.query.userProfiles, 'findFirst').mockResolvedValueOnce(stale);

      await expect(provider.refreshAccessToken(userProfileId)).rejects.toThrow(
        'the grant was replaced by a new sign-in',
      );
      expect(await storedProfile()).toMatchObject({ accessToken: 'new-access-token' });
      expect(onPermanentAuthFailure).not.toHaveBeenCalled();
    });
  });

  it('keeps a new sign-in when Entra ID rejects the grant it replaced', async () => {
    mockFetch.mockImplementation(async () => {
      await signInDuringRefresh();
      return oauthErrorResponse(400, 'invalid_grant');
    });

    const refresh = createProvider().refreshAccessToken(userProfileId);

    await expect(refresh).rejects.toThrow('the grant was replaced by a new sign-in');
    await expect(refresh).rejects.not.toBeInstanceOf(UpstreamCredentialRevokedError);
    expect(await storedProfile()).toMatchObject({
      accessToken: 'new-access-token',
      refreshToken: 'new-refresh-token',
    });
    expect(onPermanentAuthFailure).not.toHaveBeenCalled();
  });

  it('keeps a new sign-in when the refresh of the grant it replaced succeeds late', async () => {
    mockFetch.mockImplementation(async () => {
      await signInDuringRefresh();
      return tokensResponse('late-access-token', 'late-refresh-token');
    });

    await expect(createProvider().refreshAccessToken(userProfileId)).resolves.toBe(
      'late-access-token',
    );
    expect(await storedProfile()).toMatchObject({
      accessToken: 'new-access-token',
      refreshToken: 'new-refresh-token',
    });
  });

  it('does not put a new sign-in into backoff for the grant it replaced', async () => {
    mockFetch.mockImplementation(async () => {
      await signInDuringRefresh();
      throw connectTimeout();
    });

    await expect(createProvider().refreshAccessToken(userProfileId)).rejects.toThrow();
    expect(await storedProfile()).toMatchObject({
      refreshToken: 'new-refresh-token',
      tokenRefreshFailureCount: 0,
      tokenRefreshRetryAt: null,
    });
  });
});
