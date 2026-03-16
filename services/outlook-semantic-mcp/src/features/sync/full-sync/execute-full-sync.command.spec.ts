/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ExecuteFullSyncCommand, START_DELTA_LINK } from './execute-full-sync.command';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const VERSION = '00000000-0000-0000-0000-000000000001';
const IGNORED_BEFORE = new Date('2024-01-01T00:00:00Z');

function makeEmail(id: string, created: string, modified: string) {
  return {
    id,
    internetMessageId: `<${id}@example.com>`,
    createdDateTime: created,
    lastModifiedDateTime: modified,
    from: { emailAddress: { address: 'sender@example.com', name: 'Sender' } },
    subject: `Email ${id}`,
    uniqueBody: { contentType: 'text' as const, content: `Body of ${id}` },
  };
}

function makeGraphResponse(emails: ReturnType<typeof makeEmail>[], nextLink?: string) {
  return {
    value: emails,
    ...(nextLink ? { '@odata.nextLink': nextLink } : {}),
  };
}

function makeFilters() {
  return {
    ignoredBefore: IGNORED_BEFORE.toISOString(),
    ignoredSenders: [],
    ignoredContents: [],
  };
}

function makeInboxConfig(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    fullSyncState: 'fetching-emails',
    fullSyncVersion: VERSION,
    filters: makeFilters(),
    oldestCreatedDateTime: null,
    fullSyncNextLink: START_DELTA_LINK,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function createMockGraphApi() {
  const api: Record<string, any> = {
    header: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    filter: vi.fn().mockReturnThis(),
    orderby: vi.fn().mockReturnThis(),
    top: vi.fn().mockReturnThis(),
    get: vi.fn(),
  };
  return api;
}

function createMockGraphClientFactory(graphApi: ReturnType<typeof createMockGraphApi>) {
  return {
    createClientForUser: vi.fn().mockReturnValue({
      api: vi.fn().mockReturnValue(graphApi),
    }),
  };
}

function createMockAmqp() {
  return { publish: vi.fn().mockResolvedValue(undefined) };
}

function createMockSyncDirectoriesCommand() {
  return { run: vi.fn().mockResolvedValue(undefined) };
}

function createMockDb(inboxConfig: Record<string, unknown> | undefined) {
  const executeFn = vi.fn().mockResolvedValue({ rowCount: 1 });
  return {
    select: vi.fn().mockReturnValue({
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockResolvedValue(inboxConfig ? [inboxConfig] : []),
      }),
    }),
    update: vi.fn().mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: executeFn,
        }),
      }),
    }),
    __executeFn: executeFn,
  };
}

function createCommand({
  graphApi,
  amqp,
  syncDirectories,
  db,
}: {
  graphApi: ReturnType<typeof createMockGraphApi>;
  amqp: ReturnType<typeof createMockAmqp>;
  syncDirectories: ReturnType<typeof createMockSyncDirectoriesCommand>;
  db: ReturnType<typeof createMockDb>;
}): ExecuteFullSyncCommand {
  return new ExecuteFullSyncCommand(
    createMockGraphClientFactory(graphApi) as any,
    amqp as any,
    syncDirectories as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ExecuteFullSyncCommand', () => {
  let graphApi: ReturnType<typeof createMockGraphApi>;
  let amqp: ReturnType<typeof createMockAmqp>;
  let syncDirectories: ReturnType<typeof createMockSyncDirectoriesCommand>;

  beforeEach(() => {
    graphApi = createMockGraphApi();
    amqp = createMockAmqp();
    syncDirectories = createMockSyncDirectoriesCommand();
    vi.clearAllMocks();
  });

  it('fetches a single batch and sets state to ready', async () => {
    const emails = [
      makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z'),
      makeEmail('msg-2', '2024-06-02T00:00:00Z', '2024-06-02T01:00:00Z'),
    ];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // Both emails published with low priority
    expect(amqp.publish).toHaveBeenCalledTimes(2);
    for (const call of amqp.publish.mock.calls) {
      expect(call[3]).toEqual(expect.objectContaining({ priority: 1 }));
    }

    // State updated to 'ready' — last update call sets fullSyncState
    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1]?.value.set;
    expect(lastUpdateSetCall).toHaveBeenCalledWith(
      expect.objectContaining({ fullSyncState: 'ready' }),
    );
  });

  it('follows nextLink to fetch multiple batches', async () => {
    const batch1 = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    const batch2 = [makeEmail('msg-2', '2024-05-01T00:00:00Z', '2024-05-01T01:00:00Z')];

    graphApi.get
      .mockResolvedValueOnce(makeGraphResponse(batch1, 'https://graph.microsoft.com/nextPage'))
      .mockResolvedValueOnce(makeGraphResponse(batch2));

    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // Two emails total published
    expect(amqp.publish).toHaveBeenCalledTimes(2);

    // Graph API called twice (initial + nextLink)
    expect(graphApi.get).toHaveBeenCalledTimes(2);

    // State set to 'ready'
    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1]?.value.set;
    expect(lastUpdateSetCall).toHaveBeenCalledWith(
      expect.objectContaining({ fullSyncState: 'ready' }),
    );
  });

  it('discards stale event when version does not match', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncVersion: 'different-version' }));
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // Should not call graph API or publish anything
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
    expect(syncDirectories.run).not.toHaveBeenCalled();
  });

  it('discards event when state is not fetching-emails', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncState: 'ready' }));
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
    expect(syncDirectories.run).not.toHaveBeenCalled();
  });

  it('discards event when inbox configuration is not found', async () => {
    const db = createMockDb(undefined);
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('sets state to failed on Graph API error', async () => {
    graphApi.get.mockRejectedValueOnce(new Error('Graph API unavailable'));

    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    // Should NOT throw — error is caught internally
    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // State should be set to 'failed'
    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1]?.value.set;
    expect(lastUpdateSetCall).toHaveBeenCalledWith(
      expect.objectContaining({ fullSyncState: 'failed' }),
    );
  });

  it('uses createdDateTime filter when fetching via START_DELTA_LINK', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // Filter should only contain the ignoredBefore condition — no lastModifiedDateTime filter
    const filterArg = graphApi.filter.mock.calls[0]?.[0] as string;
    expect(filterArg).toContain(`createdDateTime gt ${IGNORED_BEFORE.toISOString()}`);
    expect(filterArg).not.toContain('lastModifiedDateTime');
  });

  it('returns early when fullSyncNextLink is null', async () => {
    const db = createMockDb(makeInboxConfig({ fullSyncNextLink: null }));
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(amqp.publish).not.toHaveBeenCalled();
    expect(syncDirectories.run).not.toHaveBeenCalled();
  });

  it('stops processing when version becomes stale mid-sync', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(
      makeGraphResponse(emails, 'https://graph.microsoft.com/nextPage'),
    );

    // DB where updateWatermarks returns rowCount 0 (version mismatch)
    const executeFn = vi.fn().mockResolvedValue({ rowCount: 0 });
    const db = {
      select: vi.fn().mockReturnValue({
        from: vi.fn().mockReturnValue({
          where: vi.fn().mockResolvedValue([makeInboxConfig()]),
        }),
      }),
      update: vi.fn().mockReturnValue({
        set: vi.fn().mockReturnValue({
          where: vi.fn().mockReturnValue({
            execute: executeFn,
          }),
        }),
      }),
    };

    const command = createCommand({ graphApi, amqp, syncDirectories, db: db as any });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // First batch processed and published
    expect(amqp.publish).toHaveBeenCalledTimes(1);

    // Graph API only called once — did not follow nextLink because version was stale
    expect(graphApi.get).toHaveBeenCalledTimes(1);
  });

  it('skips emails matching filter patterns', async () => {
    const emails = [
      makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z'),
      // This email is before ignoredBefore
      makeEmail('msg-old', '2023-01-01T00:00:00Z', '2023-01-01T01:00:00Z'),
    ];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // Only 1 of 2 emails should be published (the old one is filtered by shouldSkipEmail)
    expect(amqp.publish).toHaveBeenCalledTimes(1);
  });

  it('resumes from saved next link, skipping initial filter-based call', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb(
      makeInboxConfig({ fullSyncNextLink: 'https://graph.microsoft.com/savedLink' }),
    );
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // No filter-based call — resumed directly from saved link
    expect(graphApi.filter).not.toHaveBeenCalled();

    // Graph API was called to fetch from the saved link
    expect(graphApi.get).toHaveBeenCalled();

    // Email from the response was published
    expect(amqp.publish).toHaveBeenCalledTimes(1);
  });

  it('persists next link to DB after each batch', async () => {
    const batch1 = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    const batch2 = [makeEmail('msg-2', '2024-05-01T00:00:00Z', '2024-05-01T01:00:00Z')];

    graphApi.get
      .mockResolvedValueOnce(makeGraphResponse(batch1, 'https://graph.microsoft.com/nextPage2'))
      .mockResolvedValueOnce(makeGraphResponse(batch2));

    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // The set mock captures all calls. After batch 1: updateWatermarks + updateNextLink.
    // updateNextLink for batch 1 should persist the next link.
    const setCalls = db.update.mock.results[0]?.value.set.mock.calls;
    const nextLinkUpdates = setCalls.filter(
      (call: any[]) => 'fullSyncNextLink' in call[0] && !('fullSyncState' in call[0]),
    );

    expect(nextLinkUpdates[0][0]).toEqual(
      expect.objectContaining({ fullSyncNextLink: 'https://graph.microsoft.com/nextPage2' }),
    );
  });

  it('clears next link on completion', async () => {
    const emails = [makeEmail('msg-1', '2024-06-01T00:00:00Z', '2024-06-01T01:00:00Z')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(emails));

    const db = createMockDb(makeInboxConfig());
    const command = createCommand({ graphApi, amqp, syncDirectories, db });

    await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

    // Final update sets state to ready and clears next link
    const lastUpdateSetCall = db.update.mock.results[db.update.mock.calls.length - 1]?.value.set;
    expect(lastUpdateSetCall).toHaveBeenCalledWith(
      expect.objectContaining({ fullSyncState: 'ready', fullSyncNextLink: null }),
    );
  });
});
