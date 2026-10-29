import path from 'node:path';
import { type McpOAuthModuleOptions, OpaqueTokenService } from '@unique-ag/mcp-oauth';
import type { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import type { Cache } from 'cache-manager';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it } from 'vitest';
import { MockCacheManager, MockEncryptionService } from '../__mocks__';
import type { DrizzleDatabase } from '../drizzle/drizzle.module';
import * as schema from '../drizzle/schema';
import { McpOAuthStore } from './mcp-oauth.store';

const CONTAINER_STARTUP_TIMEOUT_MS = 120_000;
const CLIENT_ID = 'client-a';

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
  );
  return { store, tokenService: new OpaqueTokenService(tokenServiceOptions, store) };
}

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

  it('rejects a replayed refresh token and revokes the tokens issued from it', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    const rotated = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    expect(rotated).not.toBeNull();

    const replayed = await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(replayed).toBeNull();
    expect(await pod.tokenService.validateRefreshToken(rotated?.refresh_token ?? '')).toBeNull();
    expect(await pod.tokenService.validateAccessToken(rotated?.access_token ?? '')).toBeNull();
    expect(await pod.tokenService.validateAccessToken(initial.access_token)).toBeNull();
    expect(await db.select().from(schema.tokens)).toEqual([]);
  });

  it('rejects a refresh token replayed on another pod after it was rotated', async () => {
    const podA = createPod(db);
    const podB = createPod(db);
    const initial = await issueInitialTokens(podA.tokenService);
    // Pod B has seen the token before it was rotated.
    expect(await podB.tokenService.validateRefreshToken(initial.refresh_token)).not.toBeNull();

    const rotated = await podA.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    const replayed = await podB.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);

    expect(rotated).not.toBeNull();
    expect(replayed).toBeNull();
    expect(await podA.tokenService.validateRefreshToken(rotated?.refresh_token ?? '')).toBeNull();
  });

  it('lets exactly one of two concurrent redemptions of the same token succeed', async () => {
    const podA = createPod(db);
    const podB = createPod(db);
    const initial = await issueInitialTokens(podA.tokenService);

    const results = await Promise.all([
      podA.store.redeemRefreshToken(initial.refresh_token),
      podB.store.redeemRefreshToken(initial.refresh_token),
    ]);

    expect(results.filter(Boolean)).toHaveLength(1);
  });

  it('keeps a used refresh token until the cleanup job removes it after expiry', async () => {
    const pod = createPod(db);
    const initial = await issueInitialTokens(pod.tokenService);
    await pod.tokenService.refreshAccessToken(initial.refresh_token, CLIENT_ID);
    const usedTokenRow = eq(schema.tokens.token, initial.refresh_token);

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
