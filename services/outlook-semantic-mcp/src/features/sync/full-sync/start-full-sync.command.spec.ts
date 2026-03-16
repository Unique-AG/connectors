/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { START_DELTA_LINK } from './execute-full-sync.command';
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
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function createMockGetSubscriptionAndUserProfileQuery() {
  return {
    run: vi.fn().mockResolvedValue({
      userProfile: { id: USER_PROFILE_ID, email: 'user@example.com' },
    }),
  };
}

function createMockExecuteFullSyncCommand() {
  return { run: vi.fn().mockResolvedValue({ status: 'completed' }) };
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
  getSubscriptionAndUserProfileQuery,
  executeFullSyncCommand,
  db,
}: {
  getSubscriptionAndUserProfileQuery: ReturnType<
    typeof createMockGetSubscriptionAndUserProfileQuery
  >;
  executeFullSyncCommand: ReturnType<typeof createMockExecuteFullSyncCommand>;
  db: ReturnType<typeof createMockDb>;
}): StartFullSyncCommand {
  return new StartFullSyncCommand(
    getSubscriptionAndUserProfileQuery as any,
    executeFullSyncCommand as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('StartFullSyncCommand', () => {
  let getQuery: ReturnType<typeof createMockGetSubscriptionAndUserProfileQuery>;
  let executeFullSyncCommand: ReturnType<typeof createMockExecuteFullSyncCommand>;

  beforeEach(() => {
    getQuery = createMockGetSubscriptionAndUserProfileQuery();
    executeFullSyncCommand = createMockExecuteFullSyncCommand();
    vi.clearAllMocks();
  });

  it('always sets fullSyncNextLink to START_DELTA_LINK when starting', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncState: 'ready' }));
    const command = createCommand({ getSubscriptionAndUserProfileQuery: getQuery, executeFullSyncCommand, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');

    const setCall = db.__tx.__txUpdate.set.mock.calls[0]?.[0];
    expect(setCall).toEqual(
      expect.objectContaining({
        fullSyncState: 'running',
        fullSyncNextLink: START_DELTA_LINK,
      }),
    );
  });

  it('preserves newestLastModifiedDateTime from previous sync on resume', async () => {
    const savedModifiedDateTime = new Date('2024-06-15T00:00:00Z');
    const db = createMockDb(
      makeInboxConfig({
        fullSyncState: 'failed',
        oldestCreatedDateTime: new Date('2024-06-01T00:00:00Z'),
        newestLastModifiedDateTime: savedModifiedDateTime,
      }),
    );
    const command = createCommand({ getSubscriptionAndUserProfileQuery: getQuery, executeFullSyncCommand, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');

    const setCall = db.__tx.__txUpdate.set.mock.calls[0]?.[0];
    expect(setCall).toEqual(
      expect.objectContaining({
        fullSyncState: 'running',
        fullSyncNextLink: START_DELTA_LINK,
        newestLastModifiedDateTime: savedModifiedDateTime,
        oldestCreatedDateTime: null,
      }),
    );
  });

  it('skips when inbox configuration is missing', async () => {
    const db = createMockDb(undefined);
    const command = createCommand({ getSubscriptionAndUserProfileQuery: getQuery, executeFullSyncCommand, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('skipped');
    expect(executeFullSyncCommand.run).not.toHaveBeenCalled();
  });

  it('skips when sync is already running', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncState: 'running' }));
    const command = createCommand({ getSubscriptionAndUserProfileQuery: getQuery, executeFullSyncCommand, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('skipped');
    expect(executeFullSyncCommand.run).not.toHaveBeenCalled();
  });

  it('skips when sync ran recently', async () => {
    const oneMinuteAgo = new Date();
    oneMinuteAgo.setMinutes(oneMinuteAgo.getMinutes() - 1);

    const db = createMockDb(
      makeInboxConfig({ fullSyncState: 'ready', lastFullSyncRunAt: oneMinuteAgo }),
    );
    const command = createCommand({ getSubscriptionAndUserProfileQuery: getQuery, executeFullSyncCommand, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('skipped');
    expect(executeFullSyncCommand.run).not.toHaveBeenCalled();
  });

  it('fires execute command on successful start', async () => {
    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ getSubscriptionAndUserProfileQuery: getQuery, executeFullSyncCommand, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');
    expect(executeFullSyncCommand.run).toHaveBeenCalledWith(
      expect.objectContaining({ userProfileId: USER_PROFILE_ID, version: expect.any(String) }),
    );
  });

  it('allows start when previous sync failed', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncState: 'failed' }));
    const command = createCommand({ getSubscriptionAndUserProfileQuery: getQuery, executeFullSyncCommand, db });

    const result = await command.run(SUBSCRIPTION_ID);

    expect(result.status).toBe('started');
    expect(executeFullSyncCommand.run).toHaveBeenCalledTimes(1);
  });
});
