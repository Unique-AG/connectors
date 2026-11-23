import { createHmac } from 'node:crypto';
import path from 'node:path';
import {
  type McpOAuthModuleOptions,
  OpaqueTokenService,
  type TokenPair,
} from '@unique-ag/mcp-oauth';
import type { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import type { Cache } from 'cache-manager';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { MockCacheManager, MockEncryptionService } from '../__mocks__';
import type { DrizzleDatabase } from '../drizzle/drizzle.module';
import * as schema from '../drizzle/schema';
import { McpOAuthStore } from './mcp-oauth.store';

const CONTAINER_STARTUP_TIMEOUT_MS = 120_000;
const CLIENT_ID = 'client-a';
const HMAC_SECRET = 'integration-hmac-secret';

const tokenServiceOptions = {
  accessTokenExpiresIn: 3600,
  refreshTokenExpiresIn: 86400,
} as McpOAuthModuleOptions;

// Each pod has its own in-memory cache but shares the database.
function createPod(db: DrizzleDatabase) {
  const store = new McpOAuthStore(
    db,
    new MockEncryptionService(),
    new MockCacheManager() as unknown as Cache,
    {} as AmqpConnection,
    HMAC_SECRET,
  );
  return { store, tokenService: new OpaqueTokenService(tokenServiceOptions, store) };
}

const hashToken = (token: string) =>
  createHmac('sha256', HMAC_SECRET).update(`mcp-token:${token}`).digest('hex');

describe('McpOAuthStore against Postgres: refresh token reuse', () => {
  let container: StartedPostgreSqlContainer;
  let pool: Pool;
  let db: DrizzleDatabase;
  let userProfileId: string;

  beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start();
    pool = new Pool({ connectionString: container.getConnectionUri() });
    db = drizzle({ client: pool, casing: 'snake_case', schema });
    await migrate(db, { migrationsFolder: path.resolve(__dirname, '../../drizzle') });
  }, CONTAINER_STARTUP_TIMEOUT_MS);

  afterAll(async () => {
    await pool?.end();
    await container?.stop();
  });

  beforeEach(async () => {
    await db.delete(schema.tokens);
    await db.delete(schema.userProfiles);
    const [profile] = await db
      .insert(schema.userProfiles)
      .values({ provider: 'microsoft', providerUserId: 'user-1', username: 'user-1' })
      .returning({ id: schema.userProfiles.id });
    userProfileId = profile?.id ?? '';
  });

  async function issueInitialTokens(tokenService: OpaqueTokenService) {
    return tokenService.generateTokenPair('user-1', CLIENT_ID, 'read', 'resource', userProfileId);
  }

  it('rotates a refresh token once', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);

    const rotated = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(rotated?.refresh_token).toBeDefined();
    expect(rotated?.refresh_token).not.toBe(initial.refresh_token);
    expect(await pod.tokenService.validateRefreshToken(initial.refresh_token)).toBeNull();
    expect(await pod.tokenService.validateRefreshToken(rotated?.refresh_token ?? '')).toEqual(
      expect.objectContaining({ generation: 1 }),
    );
  });

  async function ageRedeemedToken(refreshToken: string, ageMs: number) {
    await db
      .update(schema.tokens)
      .set({ usedAt: new Date(Date.now() - ageMs) })
      .where(eq(schema.tokens.token, hashToken(refreshToken)));
  }

  it('serves the same pair when a used refresh token is replayed inside the grace window', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    const rotated = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    const replayed = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(rotated).not.toBeNull();
    expect(replayed).toEqual(rotated);
    expect(await pod.tokenService.validateRefreshToken(rotated?.refresh_token ?? '')).toEqual(
      expect.objectContaining({ generation: 1 }),
    );
  });

  it('serves the same pair on every replay inside the grace window', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    const rotated = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    const second = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    const third = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(second).toEqual(rotated);
    expect(third).toEqual(rotated);
    expect(await pod.tokenService.validateRefreshToken(rotated?.refresh_token ?? '')).toEqual(
      expect.objectContaining({ generation: 1 }),
    );
  });

  it('serves the live pair when the replayed token was rotated twice inside the grace window', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    const first = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    const second = await pod.tokenService.refreshAccessToken(first?.refresh_token ?? '', CLIENT_ID);

    const replayed = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(second).not.toBeNull();
    expect(replayed).toEqual(second);
    expect(await pod.tokenService.validateRefreshToken(second?.refresh_token ?? '')).toEqual(
      expect.objectContaining({ generation: 2 }),
    );
  });

  it('revokes the family when a used refresh token is replayed after the grace window', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    const rotated = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    await ageRedeemedToken(initial.refresh_token, 60_000);

    const replayed = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(replayed).toBeNull();
    expect(await pod.tokenService.validateRefreshToken(rotated?.refresh_token ?? '')).toBeNull();
    expect(await pod.tokenService.validateAccessToken(rotated?.access_token ?? '')).toBeNull();
    expect(await pod.tokenService.validateAccessToken(initial.access_token)).toBeNull();
    expect(await db.select().from(schema.tokens)).toEqual([]);
  });

  it('revokes the family when a used refresh token is replayed by another client', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    const rotated = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    const replayed = await pod.tokenService.refreshAccessToken(initial.refresh_token, 'client-b');

    expect(replayed).toBeNull();
    expect(await pod.tokenService.validateRefreshToken(rotated?.refresh_token ?? '')).toBeNull();
  });

  it('serves the same pair to another pod that replays the token inside the grace window', async () => {
    const podA = createPod(db);
    const podB = createPod(db);
    const initial = await issueInitialTokens(podA.tokenService);
    expect(await podB.tokenService.validateRefreshToken(initial.refresh_token)).not.toBeNull();

    const rotated = await podA.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    const replayed = await podB.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(rotated).not.toBeNull();
    expect(replayed).toEqual(rotated);
  });

  it('lets exactly one of two concurrent redemptions of the same token succeed', async () => {
    const podA = createPod(db);
    const podB = createPod(db);
    const initial = await issueInitialTokens(podA.tokenService);

    const results = await Promise.all([
      podA.store.redeemRefreshToken(initial.refresh_token, 'successor-a'),
      podB.store.redeemRefreshToken(initial.refresh_token, 'successor-b'),
    ]);

    expect(results.filter(Boolean)).toHaveLength(1);
  });

  it('serves both of two concurrent refreshes the same pair', async () => {
    const podA = createPod(db);
    const podB = createPod(db);
    const initial = await issueInitialTokens(podA.tokenService);

    const [resultA, resultB] = await Promise.all([
      podA.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID),
      podB.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID),
    ]);

    expect(resultA).not.toBeNull();
    expect(resultA).toEqual(resultB);
    const pod = createPod(db);
    expect(await pod.tokenService.validateRefreshToken(resultA?.refresh_token ?? '')).toEqual(
      expect.objectContaining({ generation: 1 }),
    );
    // The loser's own pair was removed: the initial pair and the winner's pair remain.
    expect(await db.select().from(schema.tokens)).toHaveLength(4);
  });

  it('serves the loser the pair the winner stored when the loser lost the redeem', async () => {
    const podA = createPod(db);
    const podB = createPod(db);
    const initial = await issueInitialTokens(podA.tokenService);
    let winnerResult: TokenPair | null = null;
    const redeem = podB.store.redeemRefreshToken.bind(podB.store);
    vi.spyOn(podB.store, 'redeemRefreshToken').mockImplementation(async (token, successor) => {
      winnerResult = await podA.tokenService.refreshAccessToken(token, CLIENT_ID);
      return redeem(token, successor);
    });

    const loserResult = await podB.tokenService.refreshAccessToken(
      initial.refresh_token,
      CLIENT_ID,
    );

    expect(winnerResult).not.toBeNull();
    expect(loserResult).toEqual(winnerResult);
  });

  it('revokes the winner when a loser revoked the family before the winner stored its tokens', async () => {
    const podA = createPod(db);
    const podB = createPod(db);
    const initial = await issueInitialTokens(podA.tokenService);
    let loserResult: TokenPair | null = null;
    const redeem = podA.store.redeemRefreshToken.bind(podA.store);
    vi.spyOn(podA.store, 'redeemRefreshToken').mockImplementation(async (token, successor) => {
      const redeemed = await redeem(token, successor);
      loserResult = await podB.tokenService.refreshAccessToken(token, 'client-b');
      return redeemed;
    });

    const winnerResult = await podA.tokenService.refreshAccessToken(
      initial.refresh_token,
      CLIENT_ID,
    );

    expect(winnerResult).toBeNull();
    expect(loserResult).toBeNull();
    expect(await db.select().from(schema.tokens)).toEqual([]);
  });

  it('does not accept an unused refresh token as an access token', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);

    expect(await pod.store.getAccessToken(initial.refresh_token)).toBeUndefined();
    expect(await pod.tokenService.validateAccessToken(initial.refresh_token)).toBeNull();
  });

  it('does not accept a used refresh token as an access token', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(await pod.store.getAccessToken(initial.refresh_token)).toBeUndefined();
    expect(await pod.tokenService.validateAccessToken(initial.refresh_token)).toBeNull();
  });

  it('keeps a refresh token when it is removed as an access token', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);

    await pod.store.removeAccessToken(initial.refresh_token);

    expect(await pod.store.getRefreshToken(initial.refresh_token)).toBeDefined();
  });

  it('keeps a used refresh token until the cleanup job removes it after expiry', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    const usedTokenRow = eq(schema.tokens.token, hashToken(initial.refresh_token));

    const [kept] = await db.select().from(schema.tokens).where(usedTokenRow);
    expect(kept?.usedAt).toBeInstanceOf(Date);

    await db
      .update(schema.tokens)
      .set({ expiresAt: new Date(Date.now() - 8 * 24 * 60 * 60 * 1000) })
      .where(usedTokenRow);
    await pod.store.cleanupExpiredTokens(7);

    expect(await db.select().from(schema.tokens).where(usedTokenRow)).toEqual([]);
  });
});
