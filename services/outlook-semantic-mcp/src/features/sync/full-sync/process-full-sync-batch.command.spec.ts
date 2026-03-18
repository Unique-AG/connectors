/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { START_FULL_SYNC_LINK } from './full-sync.command';
import { ProcessFullSyncBatchCommand } from './process-full-sync-batch.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
}));

vi.mock('../../mail-ingestion/utils/should-skip-email', () => ({
  shouldSkipEmail: vi.fn().mockReturnValue({ skip: false }),
}));

import { shouldSkipEmail } from '../../mail-ingestion/utils/should-skip-email';

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

function makeMessage(id: string, createdDateTime = '2024-06-01T00:00:00Z') {
  return {
    id,
    createdDateTime,
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
    ? vi.fn().mockRejectedValue(new Error('Ingestion failed'))
    : vi.fn().mockResolvedValue(undefined);
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
    createMockMetricService() as any,
  );
  vi.spyOn(command as any, 'sleep').mockResolvedValue(undefined);
  return command;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('ProcessFullSyncBatchCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(shouldSkipEmail).mockReturnValue({ skip: false } as any);
  });

  // -------------------------------------------------------------------------
  // Version mismatch on config load
  // -------------------------------------------------------------------------

  describe('version mismatch on config load', () => {
    it('returns version-mismatch when config is not found', async () => {
      const findConfig = { run: vi.fn().mockResolvedValue(null) };
      const command = createCommand({ findConfig });

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(result).toEqual({ outcome: 'version-mismatch' });
    });

    it('returns version-mismatch when nextLink is null', async () => {
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

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(result).toEqual({ outcome: 'version-mismatch' });
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

      await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      // Only msg-2 (index 2) should be processed; msg-0 and msg-1 should be skipped
      expect(ingestCommand.run).toHaveBeenCalledTimes(1);
      expect(ingestCommand.run).toHaveBeenCalledWith({
        userProfileId: USER_PROFILE_ID,
        messageId: 'msg-2',
      });
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

      await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

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
  // Burst limit
  // -------------------------------------------------------------------------

  describe('burst limit', () => {
    it('returns batch-uploaded after 100 successful ingestions', async () => {
      const messages = Array.from({ length: 110 }, (_, i) => makeMessage(`msg-${i}`));
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages));

      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, updateCommand });

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(result).toEqual({ outcome: 'batch-uploaded' });
      // Saves batch index at position 100 (the next message to process)
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncBatchIndex: 100 }),
      );
    });

    it('does not count skipped messages toward burst limit', async () => {
      const messages = Array.from({ length: 5 }, (_, i) => makeMessage(`msg-${i}`));
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse(messages));

      // Skip all messages
      vi.mocked(shouldSkipEmail).mockReturnValue({ skip: true, reason: 'filtered' } as any);

      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, ingestCommand });

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      // Should complete (not hit burst limit) since skipped messages don't count
      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).not.toHaveBeenCalled();
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

      await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncScheduledForIngestion: expect.anything() }),
      );
    });

    it('increments skipped counter when message is filtered', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));
      vi.mocked(shouldSkipEmail).mockReturnValue({ skip: true, reason: 'filtered' } as any);

      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, updateCommand });

      await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncSkipped: expect.anything() }),
      );
    });

    it('increments failedToUploadForIngestion after retries exhausted', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = createMockIngestEmailCommand(true);
      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, ingestCommand, updateCommand });

      await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      // 3 retries attempted
      expect(ingestCommand.run).toHaveBeenCalledTimes(3);

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
    it('retries ingestion up to 3 times before marking as failed', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = createMockIngestEmailCommand(true);
      const command = createCommand({ graphApi, ingestCommand });

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(3);
    });

    it('succeeds on second retry attempt', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([makeMessage('msg-1')]));

      const ingestCommand = {
        run: vi
          .fn()
          .mockRejectedValueOnce(new Error('Attempt 1 failed'))
          .mockResolvedValueOnce(undefined),
      };
      const updateCommand = createMockUpdateByVersionCommand();
      const command = createCommand({ graphApi, ingestCommand, updateCommand });

      await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(ingestCommand.run).toHaveBeenCalledTimes(2);

      // Should increment scheduledForIngestion, not failedToUpload
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({ fullSyncScheduledForIngestion: expect.anything() }),
      );
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

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      expect(result).toEqual({ outcome: 'completed' });
      expect(ingestCommand.run).toHaveBeenCalledTimes(2);
    });

    it('completes immediately on empty first page', async () => {
      const graphApi = createMockGraphApi();
      graphApi.get.mockResolvedValue(makeGraphResponse([]));

      const ingestCommand = createMockIngestEmailCommand();
      const command = createCommand({ graphApi, ingestCommand });

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

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

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

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

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

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

      const result = await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

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

      await command.run({ userProfileId: USER_PROFILE_ID, version: VERSION });

      // Watermark update should include both newestCreatedDateTime and oldestCreatedDateTime
      expect(updateCommand.run).toHaveBeenCalledWith(
        USER_PROFILE_ID,
        VERSION,
        expect.objectContaining({
          newestCreatedDateTime: expect.anything(),
          oldestCreatedDateTime: expect.anything(),
        }),
      );
    });
  });
});
