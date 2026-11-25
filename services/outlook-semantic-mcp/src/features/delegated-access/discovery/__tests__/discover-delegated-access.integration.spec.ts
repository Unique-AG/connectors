/** biome-ignore-all lint/suspicious/noExplicitAny: Graph client, config and metrics stand-ins */
import assert from 'node:assert';
import path from 'node:path';
import { UpstreamCredentialRevokedError } from '@unique-ag/mcp-oauth';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { PostgreSqlContainer, type StartedPostgreSqlContainer } from '@testcontainers/postgresql';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/node-postgres';
import { migrate } from 'drizzle-orm/node-postgres/migrator';
import type { Pool } from 'pg';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { DrizzleDatabase } from '~/db';
import * as schema from '~/db/schema';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { createPostgresPool, stopPostgres } from '../../../../__mocks__/stop-postgres';
import {
  DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
  DiscoverDelegatedAccessCommand,
} from '../discover-delegated-access.command';

vi.mock('../../../../utils/sleep', () => ({ sleep: vi.fn().mockResolvedValue(undefined) }));

const CONTAINER_STARTUP_TIMEOUT_MS = 120_000;

type UserProfile = typeof schema.userProfiles.$inferSelect;
type GraphAnswer = (delegateUserId: string, ownerEmail: string) => Promise<unknown>;

const accessGranted: GraphAnswer = async () => ({ value: [] });

const graphError = (statusCode: number) => {
  const error = new GraphError(statusCode, 'Graph error');
  error.statusCode = statusCode;
  return error;
};

describe('DiscoverDelegatedAccessCommand against Postgres', () => {
  let container: StartedPostgreSqlContainer;
  let pool: Pool;
  let db: DrizzleDatabase;
  let persistentCacheService: PersistentCacheService;
  let graphAnswer: GraphAnswer;
  let graphClientFactory: { createClientForUser: ReturnType<typeof vi.fn> };
  let command: DiscoverDelegatedAccessCommand;

  beforeAll(async () => {
    container = await new PostgreSqlContainer('postgres:17-alpine').start();
    pool = createPostgresPool(container.getConnectionUri());
    db = drizzle({ client: pool, casing: 'snake_case', schema });
    await migrate(db, { migrationsFolder: path.resolve(__dirname, '../../../../../drizzle') });
  }, CONTAINER_STARTUP_TIMEOUT_MS);

  afterAll(async () => {
    await stopPostgres(pool, container);
  });

  beforeEach(async () => {
    await db.delete(schema.delegatedAccessAccounts);
    await db.delete(schema.caches);
    await db.delete(schema.userProfiles);

    graphAnswer = accessGranted;
    graphClientFactory = {
      createClientForUser: vi.fn((delegateUserId: string) => ({
        api: (graphPath: string) => {
          // `/users/{ownerEmail}/messages`
          const ownerEmail = graphPath.split('/')[2] ?? '';
          const request = {
            top: () => request,
            select: () => request,
            get: () => graphAnswer(delegateUserId, ownerEmail),
          };
          return request;
        },
      })),
    };
    persistentCacheService = new PersistentCacheService(db);
    command = new DiscoverDelegatedAccessCommand(
      graphClientFactory as any,
      { scan: 'full_access_only' } as any,
      { mcpDebugMode: false } as any,
      db,
      persistentCacheService,
      {
        measureDiscoverRun: (fn: () => Promise<unknown>) => fn(),
        measureDiscoverUser: (fn: () => Promise<unknown>) => fn(),
      } as any,
    );
  });

  async function insertUser(
    name: string,
    overrides: Partial<typeof schema.userProfiles.$inferInsert> = {},
  ): Promise<UserProfile> {
    const [user] = await db
      .insert(schema.userProfiles)
      .values({
        provider: 'microsoft',
        providerUserId: name,
        username: name,
        email: `${name}@contoso.example`,
        source: 'oauth',
        accessToken: `${name}-access-token`,
        refreshToken: `${name}-refresh-token`,
        ...overrides,
      })
      .returning();
    assert.ok(user);
    return user;
  }

  async function discoveredAt(user: UserProfile): Promise<Date | null> {
    const [row] = await db
      .select({ discoveredAt: schema.userProfiles.delegatedAccessDiscoveredAt })
      .from(schema.userProfiles)
      .where(eq(schema.userProfiles.id, user.id));
    return row?.discoveredAt ?? null;
  }

  async function accessPairs(): Promise<string[]> {
    const rows = await db
      .select({
        delegate: schema.delegatedAccessAccounts.delegateUserId,
        owner: schema.delegatedAccessAccounts.ownerUserId,
      })
      .from(schema.delegatedAccessAccounts);
    return rows.map(({ delegate, owner }) => `${delegate}->${owner}`).sort();
  }

  const pair = (delegate: UserProfile, owner: UserProfile) => `${delegate.id}->${owner.id}`;

  const discoveryState = () =>
    persistentCacheService.get(DISCOVER_DELEGATED_ACCESS_CACHE_KEY, 'DelegatedAccessDiscovery');

  // What the scheduler publishes: a new cycle requested now.
  const newCycleRequest = () => ({ newCycleRequestedAt: Date.now() });

  const processedDelegates = () =>
    graphClientFactory.createClientForUser.mock.calls.map(([delegateUserId]) => delegateUserId);

  it('discovers every delegate in the first cycle', async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    const carol = await insertUser('carol');
    const startedAt = Date.now();

    await command.run(newCycleRequest());

    expect(await accessPairs()).toEqual(
      [
        pair(alice, bob),
        pair(alice, carol),
        pair(bob, alice),
        pair(bob, carol),
        pair(carol, alice),
        pair(carol, bob),
      ].sort(),
    );
    for (const user of [alice, bob, carol]) {
      expect((await discoveredAt(user))?.getTime()).toBeGreaterThanOrEqual(startedAt);
    }
    const state = await discoveryState();
    expect(state?.payload.state).toBe('ready');
    expect(state?.payload.cycleStartedAt).toBeGreaterThanOrEqual(startedAt);
  });

  it("keeps a failed delegate's records and reruns only that delegate", async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    const carol = await insertUser('carol');
    await command.run(newCycleRequest());

    graphAnswer = async (delegateUserId) => {
      if (delegateUserId === alice.id) {
        throw graphError(401);
      }
      return { value: [] };
    };
    await command.run(newCycleRequest());

    expect(await accessPairs()).toContain(pair(alice, bob));
    expect(await accessPairs()).toContain(pair(alice, carol));
    const cycleStartedAt = (await discoveryState())?.payload.cycleStartedAt;
    assert.ok(cycleStartedAt);
    expect((await discoveredAt(alice))?.getTime()).toBeLessThan(cycleStartedAt);
    expect((await discoveredAt(bob))?.getTime()).toBeGreaterThanOrEqual(cycleStartedAt);
    expect((await discoveryState())?.payload.state).toBe('ready');
    await expect(command.hasPendingDelegates(new Date(cycleStartedAt))).resolves.toBe(true);

    graphAnswer = accessGranted;
    graphClientFactory.createClientForUser.mockClear();
    await command.run({});

    expect(processedDelegates()).toEqual([alice.id]);
    expect((await discoveredAt(alice))?.getTime()).toBeGreaterThanOrEqual(cycleStartedAt);
    await expect(command.hasPendingDelegates(new Date(cycleStartedAt))).resolves.toBe(false);
  });

  it('keeps going after a delegate exhausts its rate limit retries', async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    graphAnswer = async (delegateUserId) => {
      if (delegateUserId === alice.id) {
        throw graphError(429);
      }
      return { value: [] };
    };

    await command.run(newCycleRequest());

    expect(await discoveredAt(alice)).toBeNull();
    expect(await discoveredAt(bob)).not.toBeNull();
    expect(await accessPairs()).toEqual([pair(bob, alice)]);
  });

  it("clears a delegate's records when its Microsoft grant is permanently invalid", async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    await command.run(newCycleRequest());

    graphAnswer = async (delegateUserId) => {
      if (delegateUserId === alice.id) {
        throw new UpstreamCredentialRevokedError('invalid_grant');
      }
      return { value: [] };
    };
    await command.run(newCycleRequest());

    expect(await accessPairs()).toEqual([pair(bob, alice)]);
  });

  it("clears a delegate's records when its revoked grant arrives as the Graph SDK's GraphError", async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    await command.run(newCycleRequest());

    // The SDK rethrows a middleware's error as its own GraphError, keeping the name as `code`.
    graphAnswer = async (delegateUserId) => {
      if (delegateUserId === alice.id) {
        throw Object.assign(new GraphError(-1, 'Re-authentication required'), {
          code: 'UpstreamCredentialRevokedError',
        });
      }
      return { value: [] };
    };
    await command.run(newCycleRequest());

    expect(await accessPairs()).toEqual([pair(bob, alice)]);
  });

  it("clears a delegate's records when a plain 401 rejects before another owner check reports the revoked grant", async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    const carol = await insertUser('carol');
    await command.run(newCycleRequest());

    graphAnswer = async (delegateUserId, ownerEmail) => {
      if (delegateUserId === alice.id && ownerEmail === bob.email) {
        throw graphError(401);
      }
      if (delegateUserId === alice.id) {
        await new Promise((resolve) => setTimeout(resolve, 20));
        throw new UpstreamCredentialRevokedError('invalid_grant');
      }
      return { value: [] };
    };
    await command.run(newCycleRequest());

    expect(await accessPairs()).toEqual(
      [pair(bob, alice), pair(bob, carol), pair(carol, alice), pair(carol, bob)].sort(),
    );
  });

  it('leaves a delegate pending when one of its owner checks fails, and the rerun covers it', async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    const carol = await insertUser('carol');
    graphAnswer = async (delegateUserId, ownerEmail) => {
      if (delegateUserId === alice.id && ownerEmail === carol.email) {
        throw graphError(500);
      }
      return { value: [] };
    };

    await command.run(newCycleRequest());

    expect(await discoveredAt(alice)).toBeNull();
    expect(await discoveredAt(bob)).not.toBeNull();
    expect(await accessPairs()).toContain(pair(alice, bob));

    graphAnswer = accessGranted;
    graphClientFactory.createClientForUser.mockClear();
    await command.run({});

    expect(processedDelegates()).toEqual([alice.id]);
    expect(await accessPairs()).toContain(pair(alice, carol));
  });

  it('keeps the claim of the run that took over from a stale one', async () => {
    await insertUser('alice');
    await insertUser('bob');
    await command.run(newCycleRequest());

    // Run A claims, then stops making progress; run B takes over the claim.
    const staleRun = await command.decide(newCycleRequest());
    assert.ok(staleRun.action === 'proceed');
    const claim = (await discoveryState())?.payload;
    assert.ok(claim);
    await persistentCacheService.set(DISCOVER_DELEGATED_ACCESS_CACHE_KEY, {
      dataType: 'DelegatedAccessDiscovery',
      payload: { ...claim, lastProgressRegisteredAt: Date.now() - 11 * 60_000 },
    });
    const takeover = await command.decide({});
    assert.ok(takeover.action === 'proceed');

    // Run A finishes late: its final write must not replace B's claim.
    const ownsClaim = await (command as any).updateClaim(staleRun.runId, { state: 'ready' });

    expect(ownsClaim).toBe(false);
    expect((await discoveryState())?.payload).toEqual(
      expect.objectContaining({ state: 'running', runId: takeover.runId }),
    );
  });

  it('keeps the newer stamp when a stale run finishes the same delegate later', async () => {
    const alice = await insertUser('alice');
    await insertUser('bob');
    const staleRun = await command.decide(newCycleRequest());
    assert.ok(staleRun.action === 'proceed');
    // Run B, which took over, already stamped alice with a time after run A started its checks.
    const newerStamp = new Date(Date.now() + 60_000);
    await db
      .update(schema.userProfiles)
      .set({ delegatedAccessDiscoveredAt: newerStamp })
      .where(eq(schema.userProfiles.id, alice.id));

    const outcome = await (command as any).runDiscoveryForDelegatedUser(alice.id, staleRun.runId);

    expect(outcome).toBe('discovered');
    expect(await discoveredAt(alice)).toEqual(newerStamp);
  });

  it('skips a delegate whose token refresh is backing off until the backoff has passed', async () => {
    const alice = await insertUser('alice', {
      tokenRefreshRetryAt: new Date(Date.now() + 5 * 60_000),
    });
    const bob = await insertUser('bob');

    await command.run(newCycleRequest());

    expect(processedDelegates()).toEqual([bob.id]);
    const cycleStartedAt = new Date((await discoveryState())?.payload.cycleStartedAt ?? 0);
    await expect(command.hasPendingDelegates(cycleStartedAt)).resolves.toBe(false);

    await db
      .update(schema.userProfiles)
      .set({ tokenRefreshRetryAt: new Date(Date.now() - 60_000) })
      .where(eq(schema.userProfiles.id, alice.id));
    await expect(command.hasPendingDelegates(cycleStartedAt)).resolves.toBe(true);

    graphClientFactory.createClientForUser.mockClear();
    await command.run({});

    expect(processedDelegates()).toEqual([alice.id]);
  });

  it('processes no delegate again until a new cycle starts', async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    await command.run(newCycleRequest());

    graphClientFactory.createClientForUser.mockClear();
    await command.run({});
    expect(processedDelegates()).toEqual([]);

    await command.run(newCycleRequest());
    expect(processedDelegates().sort()).toEqual([alice.id, bob.id].sort());
  });

  it('picks up a user who connected after the cycle started', async () => {
    await insertUser('alice');
    await insertUser('bob');
    await command.run(newCycleRequest());
    const cycleStartedAt = new Date((await discoveryState())?.payload.cycleStartedAt ?? 0);

    const dave = await insertUser('dave');
    await expect(command.hasPendingDelegates(cycleStartedAt)).resolves.toBe(true);

    graphClientFactory.createClientForUser.mockClear();
    await command.run({});

    expect(processedDelegates()).toEqual([dave.id]);
  });

  it('checks shared mailboxes as owners but never uses them or signed-out users as delegates', async () => {
    const alice = await insertUser('alice');
    const shared = await insertUser('shared', {
      source: 'shared-mailbox',
      accessToken: null,
      refreshToken: null,
    });
    await insertUser('signed-out', { accessToken: null, refreshToken: null });

    await command.run(newCycleRequest());

    expect(processedDelegates()).toEqual([alice.id]);
    expect(await accessPairs()).toEqual([pair(alice, shared)]);
  });

  it('keeps a new cycle requested while another run is in progress', async () => {
    await insertUser('alice');
    await insertUser('bob');
    await command.run(newCycleRequest());
    const previousCycle = (await discoveryState())?.payload.cycleStartedAt;
    assert.ok(previousCycle);

    // Another pod is mid-run and reported progress a moment ago.
    await persistentCacheService.set(DISCOVER_DELEGATED_ACCESS_CACHE_KEY, {
      dataType: 'DelegatedAccessDiscovery',
      payload: {
        state: 'running',
        cycleStartedAt: previousCycle,
        lastProgressRegisteredAt: Date.now(),
      },
    });

    const decision = await command.decide(newCycleRequest());

    expect(decision.action).toBe('skip');
    const requestedCycle = (await discoveryState())?.payload.cycleStartedAt;
    assert.ok(requestedCycle);
    expect(requestedCycle).toBeGreaterThan(previousCycle);
    await expect(command.hasPendingDelegates(new Date(requestedCycle))).resolves.toBe(true);
  });

  it('continues the cycle when the scheduled request is redelivered after the run was killed', async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    const carol = await insertUser('carol');
    const scheduledRequest = newCycleRequest();

    // The run starts the cycle, finishes alice and is killed: its progress goes stale.
    await command.decide(scheduledRequest);
    const cycleStartedAt = (await discoveryState())?.payload.cycleStartedAt;
    assert.ok(cycleStartedAt);
    await db
      .update(schema.userProfiles)
      .set({ delegatedAccessDiscoveredAt: new Date() })
      .where(eq(schema.userProfiles.id, alice.id));
    await persistentCacheService.set(DISCOVER_DELEGATED_ACCESS_CACHE_KEY, {
      dataType: 'DelegatedAccessDiscovery',
      payload: {
        state: 'running',
        cycleStartedAt,
        lastProgressRegisteredAt: Date.now() - 11 * 60_000,
      },
    });

    // RabbitMQ redelivers the unacknowledged request to the restarted pod.
    await command.run(scheduledRequest);

    expect(processedDelegates().sort()).toEqual([bob.id, carol.id].sort());
    expect((await discoveryState())?.payload).toEqual(
      expect.objectContaining({ state: 'ready', cycleStartedAt }),
    );
  });

  it('continues from a discovery state written before cycles were tracked', async () => {
    const alice = await insertUser('alice');
    const bob = await insertUser('bob');
    // Written raw, as the previous release stored it, bypassing today's schema.
    await db.insert(schema.caches).values({
      key: `cacheKey_${DISCOVER_DELEGATED_ACCESS_CACHE_KEY}`,
      data: {
        dataType: 'DelegatedAccessDiscovery',
        payload: {
          state: 'failed',
          lastProcessedDelegateId: alice.id,
          lastProcessedOwnerIdForDelegate: bob.id,
          lastProgressRegisteredAt: Date.now() - 60 * 60_000,
        },
      },
    } as any);

    await command.run({});

    expect(processedDelegates().sort()).toEqual([alice.id, bob.id].sort());
    expect((await discoveryState())?.payload).toEqual(
      expect.objectContaining({ state: 'ready', cycleStartedAt: expect.any(Number) }),
    );
  });
});
