/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { START_FULL_SYNC_LINK } from './full-sync.command';
import { ProcessFullSyncBatchCommand } from './process-full-sync-batch.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const VERSION = 'test-version-uuid';
const _DEFAULT_FILTERS = {
  ignoredBefore: new Date('2020-01-01'),
  ignoredSenders: [],
  ignoredContents: [],
};

const MOCK_USER_PROFILE = {
  id: USER_PROFILE_ID,
  provider: 'azure',
  providerUserId: 'provider-user-id',
  username: 'test@example.com',
  email: 'test@example.com',
  displayName: null,
  avatarUrl: null,
  raw: null,
  accessToken: null,
  refreshToken: null,
  createdAt: new Date('2024-01-01'),
  updatedAt: new Date('2024-01-01'),
};

function makeMessage(id: string, dateTime = '2024-06-01T00:00:00Z') {
  return {
    id,
    createdDateTime: dateTime,
    receivedDateTime: dateTime,
    lastModifiedDateTime: dateTime,
    parentFolderId: 'folder-id',
    webLink: 'https://outlook.office.com/mail/id',
    from: { emailAddress: { address: 'test@example.com' } },
    subject: 'Test',
    uniqueBody: { content: 'body', contentType: 'text' as const },
  };
}

function makeGraphResponse(messages: ReturnType<typeof makeMessage>[], nextLink?: string) {
  return {
    value: messages,
    ...(nextLink ? { '@odata.nextLink': nextLink } : {}),
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

function createMockIngestEmailCommand(shouldFail = false) {
  const run = shouldFail
    ? vi.fn().mockResolvedValue('failed')
    : vi.fn().mockResolvedValue('ingested');
  return { run };
}

function createMockUpdateByVersionCommand(success = true) {
  return { run: vi.fn().mockResolvedValue(success) };
}

function createMockFindConfigByVersion(config?: {
  fullSyncNextLink: string | null;
  fullSyncBatchIndex: number;
  filters: Record<string, unknown>;
  oldestCreatedDateTime?: Date | null;
  newestCreatedDateTime?: Date | null;
}) {
  const defaultConfig = config ?? {
    fullSyncNextLink: START_FULL_SYNC_LINK,
    fullSyncBatchIndex: 0,
    fullSyncExpectedTotal: null,
    fullSyncSkipped: 0,
    fullSyncScheduledForIngestion: 0,
    fullSyncFailedToUploadForIngestion: 0,
    filters: {
      ignoredBefore: '2020-01-01T00:00:00.000Z',
      ignoredSenders: [],
      ignoredContents: [],
    },
    oldestCreatedDateTime: null,
    newestCreatedDateTime: null,
  };
  return { run: vi.fn().mockResolvedValue(defaultConfig) };
}

function createMockMetricService() {
  return {
    getHistogram: vi.fn().mockReturnValue({ record: vi.fn() }),
    getCounter: vi.fn().mockReturnValue({ add: vi.fn() }),
  };
}

function createMockUniqueApi() {
  return {
    files: { getByKeys: vi.fn().mockResolvedValue([]) },
  };
}

function createCommand({
  graphApi = createMockGraphApi(),
  ingestCommand = createMockIngestEmailCommand(),
  updateCommand = createMockUpdateByVersionCommand(),
  findConfig = createMockFindConfigByVersion(),
}: {
  graphApi?: ReturnType<typeof createMockGraphApi>;
  ingestCommand?: ReturnType<typeof createMockIngestEmailCommand>;
  updateCommand?: ReturnType<typeof createMockUpdateByVersionCommand>;
  findConfig?: ReturnType<typeof createMockFindConfigByVersion>;
} = {}) {
  const command = new ProcessFullSyncBatchCommand(
    createMockGraphClientFactory(graphApi) as any,
    ingestCommand as any,
    updateCommand as any,
    findConfig as any,
    createMockUniqueApi() as any,
    createMockMetricService() as any,
  );
  return command;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ProcessFullSyncBatchCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  // Version mismatch on config load
  // -------------------------------------------------------------------------

  describe('version mismatch on config load', () => {
    it('returns version-mismatch when config is not found', async () => {
      const findConfig = { run: vi.fn().mockResolvedValue(null) };
      const command = createCommand({ findConfig });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'version-mismatch' });
    });

    it('returns missing-full-sync-next-link when nextLink is null', async () => {
      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: null,
        fullSyncBatchIndex: 0,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const command = createCommand({ findConfig });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'missing-full-sync-next-link' });
    });
  });

  // -------------------------------------------------------------------------
  // Resume from batch index
  // -------------------------------------------------------------------------

  describe('resume from batch index', () => {
    it('resumes processing from saved batch index', async () => {
      const messages = [makeMessage('msg-0'), makeMessage('msg-1'), makeMessage('msg-2')];
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 2,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, ingestCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      // Only msg-2 (index 2) should be processed; msg-0 and msg-1 should be skipped
      expect(ingestCommand.run).toHaveBeenCalledTimes(1);
      expect(ingestCommand.run).toHaveBeenCalledWith(
        expect.objectContaining({
          graphMessage: expect.objectContaining({ id: 'msg-2' }),
        }),
      );
    });

    it('resets batch index to 0 when moving to next page', async () => {
      const page1 = [makeMessage('msg-0')];
      const page2 = [makeMessage('msg-1')];
      const graphApi = createMockGraphApi();
      graphApi.get
        .mockResolvedValueOnce(makeGraphResponse(page1, 'https://graph.microsoft.com/next'))
        .mockResolvedValueOnce(makeGraphResponse(page2));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 0,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const updateCommand = createMockUpdateByVersionCommand();
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, updateCommand, ingestCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      // Both messages processed
      expect(ingestCommand.run).toHaveBeenCalledTimes(2);

      // After page 1 completes, batch index reset to 0 + nextLink saved
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({
          fullSyncBatchIndex: 0,
          fullSyncNextLink: 'https://graph.microsoft.com/next',
        }),
      );
    });
  });

  // -------------------------------------------------------------------------
  // batchIndex vs page size edge cases
  // -------------------------------------------------------------------------

  describe('batchIndex vs page size edge cases', () => {
    it('does not infinite-loop when batchIndex exceeds shrunken page (advances to next page)', async () => {
      // Core regression test: batchIndex=5 but re-fetched page only has 3 items.
      // Without the fix the while-loop would re-fetch the same page forever.
      const page1 = [makeMessage('msg-0'), makeMessage('msg-1'), makeMessage('msg-2')];
      const page2 = [makeMessage('msg-3')];
      const graphApi = createMockGraphApi();
      graphApi.get
        .mockResolvedValueOnce(makeGraphResponse(page1, 'https://graph.microsoft.com/page2'))
        .mockResolvedValueOnce(makeGraphResponse(page2));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 5,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      // Page 1 fetched once then advanced — not fetched repeatedly
      expect(graphApi.get).toHaveBeenCalledTimes(2);
      // Only page 2 message ingested (page 1 was fully skipped)
      expect(ingestCommand.run).toHaveBeenCalledTimes(1);
      expect(ingestCommand.run).toHaveBeenCalledWith(
        expect.objectContaining({
          graphMessage: expect.objectContaining({ id: 'msg-3' }),
        }),
      );
    });

    it('advances when batchIndex equals page size exactly (off-by-one boundary)', async () => {
      // batchIndex=3 === page.length=3 → for-loop condition `i < 3` is immediately false
      const page1 = [makeMessage('msg-0'), makeMessage('msg-1'), makeMessage('msg-2')];
      const page2 = [makeMessage('msg-3')];
      const graphApi = createMockGraphApi();
      graphApi.get
        .mockResolvedValueOnce(makeGraphResponse(page1, 'https://graph.microsoft.com/page2'))
        .mockResolvedValueOnce(makeGraphResponse(page2));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 3,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(1);
      expect(ingestCommand.run).toHaveBeenCalledWith(
        expect.objectContaining({
          graphMessage: expect.objectContaining({ id: 'msg-3' }),
        }),
      );
    });

    it('completes without processing when batchIndex exceeds last page (no nextLink)', async () => {
      // batchIndex=5, page has 3 items, no nextLink → should complete, not hang
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(
        makeGraphResponse([makeMessage('msg-0'), makeMessage('msg-1'), makeMessage('msg-2')]),
      );

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 5,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).not.toHaveBeenCalled();
    });

    it('saves batchIndex as 0 and advances nextLink when page is treated as fully consumed', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get
        .mockResolvedValueOnce(
          makeGraphResponse(
            [makeMessage('msg-0'), makeMessage('msg-1')],
            'https://graph.microsoft.com/page2',
          ),
        )
        .mockResolvedValueOnce(makeGraphResponse([]));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 5,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, findConfig, updateCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      // Watermark update should save batchIndex=0 and advance nextLink
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({
          fullSyncBatchIndex: 0,
          fullSyncNextLink: 'https://graph.microsoft.com/page2',
        }),
      );
    });

    it('handles batchIndex=1 on single-item page (equals page.length boundary)', async () => {
      // batchIndex=1, page.length=1 → for-loop skipped, treated as consumed
      const page1 = [makeMessage('msg-0')];
      const page2 = [makeMessage('msg-1')];
      const graphApi = createMockGraphApi();
      graphApi.get
        .mockResolvedValueOnce(makeGraphResponse(page1, 'https://graph.microsoft.com/page2'))
        .mockResolvedValueOnce(makeGraphResponse(page2));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 1,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(1);
      expect(ingestCommand.run).toHaveBeenCalledWith(
        expect.objectContaining({
          graphMessage: expect.objectContaining({ id: 'msg-1' }),
        }),
      );
    });

    it('completes when batchIndex > 0 and page is empty', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([]));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 3,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).not.toHaveBeenCalled();
    });

    it('processes remaining messages when batchIndex is within range of a shrunken page', async () => {
      // batchIndex=1, page shrank from 5 to 3 → still processes indices 1 and 2
      const messages = [makeMessage('msg-0'), makeMessage('msg-1'), makeMessage('msg-2')];
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages));

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 1,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, findConfig, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(2);
      expect(ingestCommand.run).toHaveBeenCalledWith(
        expect.objectContaining({
          graphMessage: expect.objectContaining({ id: 'msg-1' }),
        }),
      );
      expect(ingestCommand.run).toHaveBeenCalledWith(
        expect.objectContaining({
          graphMessage: expect.objectContaining({ id: 'msg-2' }),
        }),
      );
    });

    it('returns batch-uploaded (not infinite-loop) when batchIndex exceeds page and more pages remain', async () => {
      // batchIndex=50, page has 3 items, nextLink exists. After skipping page 1,
      // page 2 has 100+ items triggering burst limit.
      const page1 = [makeMessage('msg-0'), makeMessage('msg-1'), makeMessage('msg-2')];
      const page2Messages = Array.from({ length: 110 }, (_, i) => makeMessage(`msg-p2-${i}`));
      const graphApi = createMockGraphApi();
      graphApi.get
        .mockResolvedValueOnce(makeGraphResponse(page1, 'https://graph.microsoft.com/page2'))
        .mockResolvedValueOnce(
          makeGraphResponse(page2Messages, 'https://graph.microsoft.com/page3'),
        );

      const findConfig = createMockFindConfigByVersion({
        fullSyncNextLink: START_FULL_SYNC_LINK,
        fullSyncBatchIndex: 50,
        filters: {
          ignoredBefore: '2020-01-01T00:00:00.000Z',
          ignoredSenders: [],
          ignoredContents: [],
        },
      });
      const command = createCommand({ graphApi, findConfig });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'batch-uploaded' });
    });
  });

  // -------------------------------------------------------------------------
  // Burst limit
  // -------------------------------------------------------------------------

  describe('burst limit', () => {
    it('returns batch-uploaded after at least 110 successful ingestions', async () => {
      const messages = Array.from({ length: 110 }, (_, i) => makeMessage(`msg-${i}`));
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages, `NEXT_LINK`));

      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, updateCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'batch-uploaded' });
      // Saves batch index at position 100 (the next message to process)
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncBatchIndex: 110 }),
      );
    });

    it('returns completed when burst limit is hit on last message of last page', async () => {
      // Exactly 100 messages on a single page with no nextLink — this is the last page
      const messages = Array.from({ length: 100 }, (_, i) => makeMessage(`msg-${i}`));
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages));

      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, updateCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      // Must be 'completed', NOT 'batch-uploaded'.
      // Previously this returned 'batch-uploaded' and saved fullSyncNextLink=null,
      // which acquireLockAndDecide treated as a fresh start → infinite restart loop.
      expect(result).toEqual({ outcome: 'completed' });
    });

    it('does not count skipped messages toward burst limit', async () => {
      const messages = Array.from({ length: 5 }, (_, i) => makeMessage(`msg-${i}`));
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages));

      // Return 'skipped' to simulate filtered messages
      const ingestCommand = { run: vi.fn().mockResolvedValue('skipped') };
      const command = createCommand({ graphApi, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      // Should complete (not hit burst limit) since skipped messages don't count
      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(5);
    });
  });

  // -------------------------------------------------------------------------
  // Counter increments
  // -------------------------------------------------------------------------

  describe('counter increments', () => {
    it('increments scheduledForIngestion on successful ingestion', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, updateCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncScheduledForIngestion: expect.anything() }),
      );
    });

    it('increments skipped counter when message is filtered', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = { run: vi.fn().mockResolvedValue('skipped') };
      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, ingestCommand, updateCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncSkipped: expect.anything() }),
      );
    });

    it('increments failedToUploadForIngestion when ingestion returns failed', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = createMockIngestEmailCommand(true);
      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, ingestCommand, updateCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      // Failed counter incremented
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncFailedToUploadForIngestion: expect.anything() }),
      );
    });
  });

  // -------------------------------------------------------------------------
  // Retry logic
  // -------------------------------------------------------------------------

  describe('retry logic', () => {
    it('marks message as failed when ingestEmailCommand.run returns failed', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = createMockIngestEmailCommand(true);
      const command = createCommand({ graphApi, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(1);
    });

    it('marks message as ingested when ingestEmailCommand.run returns ingested', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = { run: vi.fn().mockResolvedValue('ingested') };
      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, ingestCommand, updateCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(ingestCommand.run).toHaveBeenCalledTimes(1);

      // Should increment scheduledForIngestion, not failedToUpload
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncScheduledForIngestion: expect.anything() }),
      );
    });

    it('throws immediately on BottleneckError without retrying', async () => {
      const Bottleneck = await import('bottleneck');
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = {
        run: vi
          .fn()
          .mockRejectedValue(
            new Bottleneck.default.BottleneckError('This job has been dropped by Bottleneck'),
          ),
      };
      const command = createCommand({ graphApi, ingestCommand });

      await expect(
        command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION }),
      ).rejects.toThrow(Bottleneck.default.BottleneckError);

      // Should NOT retry — only one call
      expect(ingestCommand.run).toHaveBeenCalledTimes(1);
    });
  });

  // -------------------------------------------------------------------------
  // Page traversal
  // -------------------------------------------------------------------------

  describe('page traversal', () => {
    it('completes when all pages are processed', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get
        .mockResolvedValueOnce(
          makeGraphResponse([makeMessage('msg-1')], 'https://graph.microsoft.com/page2'),
        )
        .mockResolvedValueOnce(makeGraphResponse([makeMessage('msg-2')]));

      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(2);
    });

    it('completes immediately on empty first page', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([]));

      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, ingestCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).not.toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Version mismatch during processing
  // -------------------------------------------------------------------------

  describe('version mismatch during processing', () => {
    it('returns version-mismatch when counter update fails', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const updateCommand = createMockUpdateByVersionCommand(false);
      const command = createCommand({ graphApi, updateCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'version-mismatch' });
    });

    it('returns version-mismatch when page boundary save fails', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(
        makeGraphResponse([makeMessage('msg-1')], 'https://graph.microsoft.com/next'),
      );

      // First call (counter increment) succeeds, second call (page boundary save) fails
      const updateCommand = {
        run: vi.fn().mockResolvedValueOnce(true).mockResolvedValueOnce(false),
      };
      const command = createCommand({ graphApi, updateCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'version-mismatch' });
    });

    it('returns version-mismatch when burst limit save fails', async () => {
      const messages = Array.from({ length: 101 }, (_, i) => makeMessage(`msg-${i}`));
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages));

      // All counter increments succeed, but the burst limit save fails
      let callCount = 0;
      const updateCommand = {
        run: vi.fn().mockImplementation(() => {
          callCount++;
          // Fail on the 101st call (the burst limit save)
          return Promise.resolve(callCount <= 100);
        }),
      };
      const command = createCommand({ graphApi, updateCommand });

      const result = await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(result).toEqual({ outcome: 'version-mismatch' });
    });
  });

  // -------------------------------------------------------------------------
  // Watermark updates
  // -------------------------------------------------------------------------

  describe('watermark updates', () => {
    it('updates watermarks after processing a page', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(
        makeGraphResponse([
          makeMessage('msg-1', '2024-06-01T00:00:00Z'),
          makeMessage('msg-2', '2024-06-02T00:00:00Z'),
        ]),
      );

      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, updateCommand });

      await command.run({ userProfile: MOCK_USER_PROFILE as any, version: VERSION });

      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({
          newestReceivedEmailDateTime: expect.anything(),
          oldestReceivedEmailDateTime: expect.anything(),
        }),
      );
    });
  });
});
