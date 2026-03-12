/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { StartFullSyncCommand } from './start-full-sync.command';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const SUBSCRIPTION_ID = 'sub-001';
const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

function makeInboxConfig(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    fullSyncState: 'ready',
    lastFullSyncRunAt: null,
    filters: { ignoredBefore: '2024-01-01T00:00:00Z', ignoredSenders: [], ignoredContents: [] },
    oldestCreatedDateTime: null,
    newestLastModifiedDateTime: null,
    oldestLastModifiedDateTime: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function createMockAmqp() {
  return { publish: vi.fn().mockResolvedValue(undefined) };
}

function createMockGetSubscriptionAndUserProfileQuery() {
  return {
    run: vi.fn().mockResolvedValue({
      userProfile: { id: USER_PROFILE_ID, email: 'user@example.com' },
    }),
  };
}

function createMockDb(inboxConfig: Record<string, unknown> | undefined) {
  const txExecuteFn = vi.fn().mockResolvedValue(undefined);
  const txUpdate = {
    set: vi.fn().mockReturnValue({
      where: vi.fn().mockReturnValue({
        execute: txExecuteFn,
      }),
    }),
  };
  const tx = {
    select: vi.fn().mockReturnValue({
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          for: vi.fn().mockResolvedValue(inboxConfig ? [inboxConfig] : []),
        }),
      }),
    }),
    update: vi.fn().mockReturnValue(txUpdate),
    __txUpdate: txUpdate,
    __txExecuteFn: txExecuteFn,
  };

  return {
    transaction: vi.fn(async (cb: (tx: any) => Promise<any>) => cb(tx)),
    __tx: tx,
  };
}

function createCommand({
  amqp,
  getSubscriptionAndUserProfileQuery,
  db,
}: {
  amqp: ReturnType<typeof createMockAmqp>;
  getSubscriptionAndUserProfileQuery: ReturnType<
    typeof createMockGetSubscriptionAndUserProfileQuery
  >;
  db: ReturnType<typeof createMockDb>;
}): StartFullSyncCommand {
  return new StartFullSyncCommand(
    amqp as any,
    getSubscriptionAndUserProfileQuery as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('StartFullSyncCommand', () => {
  let amqp: ReturnType<typeof createMockAmqp>;
  let getQuery: ReturnType<typeof createMockGetSubscriptionAndUserProfileQuery>;

  beforeEach(() => {
    amqp = createMockAmqp();
    getQuery = createMockGetSubscriptionAndUserProfileQuery();
    vi.clearAllMocks();
  });

  it('clears fullSyncNextLink on fresh sync', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncState: 'ready' }));
    const command = createCommand({ amqp, getSubscriptionAndUserProfileQuery: getQuery, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');

    const setCall = db.__tx.__txUpdate.set.mock.calls[0]?.[0];
    expect(setCall).toEqual(
      expect.objectContaining({
        fullSyncState: 'fetching-emails',
        fullSyncNextLink: null,
      }),
    );
  });

  it('preserves fullSyncNextLink on resume (failed state with existing watermark)', async () => {
    const db = createMockDb(
      makeInboxConfig({
        fullSyncState: 'failed',
        oldestCreatedDateTime: new Date('2024-06-01T00:00:00Z'),
        newestLastModifiedDateTime: new Date('2024-06-15T00:00:00Z'),
      }),
    );
    const command = createCommand({ amqp, getSubscriptionAndUserProfileQuery: getQuery, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');

    const setCall = db.__tx.__txUpdate.set.mock.calls[0]?.[0];
    expect(setCall).toEqual(expect.objectContaining({ fullSyncState: 'fetching-emails' }));
    expect(setCall).not.toHaveProperty('fullSyncNextLink');
  });

  it('skips when inbox configuration is missing', async () => {
    const db = createMockDb(undefined);
    const command = createCommand({ amqp, getSubscriptionAndUserProfileQuery: getQuery, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('skipped');
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('skips when sync is already running', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncState: 'fetching-emails' }));
    const command = createCommand({ amqp, getSubscriptionAndUserProfileQuery: getQuery, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('skipped');
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('skips when sync ran recently', async () => {
    const oneMinuteAgo = new Date();
    oneMinuteAgo.setMinutes(oneMinuteAgo.getMinutes() - 1);

    const db = createMockDb(
      makeInboxConfig({ fullSyncState: 'ready', lastFullSyncRunAt: oneMinuteAgo }),
    );
    const command = createCommand({ amqp, getSubscriptionAndUserProfileQuery: getQuery, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('skipped');
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('publishes execute event on successful start', async () => {
    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ amqp, getSubscriptionAndUserProfileQuery: getQuery, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');
    expect(amqp.publish).toHaveBeenCalledTimes(1);
    expect(amqp.publish).toHaveBeenCalledWith(
      expect.any(String),
      'unique.outlook-semantic-mcp.full-sync.execute',
      expect.objectContaining({
        type: 'unique.outlook-semantic-mcp.full-sync.execute',
        payload: expect.objectContaining({ userProfileId: USER_PROFILE_ID }),
      }),
    );
  });

  it('allows start when previous sync failed', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncState: 'failed' }));
    const command = createCommand({ amqp, getSubscriptionAndUserProfileQuery: getQuery, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');
    expect(amqp.publish).toHaveBeenCalledTimes(1);
  });
});
