/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { createHash } from 'node:crypto';
import { GraphError } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SHARED_MAILBOX_SYNC_CACHE_KEY,
  SharedMailboxSyncService,
} from './shared-mailbox-sync.service';

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------

vi.mock('~/utils/sleep', () => ({ sleep: vi.fn().mockResolvedValue(undefined) }));

const mockJobStart = vi.fn();
const mockJobStop = vi.fn();
vi.mock('cron', () => ({
  CronJob: vi.fn().mockImplementation(() => ({ start: mockJobStart, stop: mockJobStop })),
}));

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CRON_SCHEDULE = '0 */6 * * *';

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function makeGraphError(statusCode: number): GraphError {
  const err = new GraphError(statusCode, 'Graph error');
  err.statusCode = statusCode;
  return err;
}

interface GraphUser {
  id: string;
  mail: string | null;
  displayName: string | null;
}

interface GraphPage {
  value: GraphUser[];
  '@odata.nextLink'?: string;
}

/**
 * Builds a mock Graph client whose api chain cycles through the given pages.
 * An element can be an Error to simulate a thrown error on that call.
 */
function makeGraphClient(pages: Array<GraphPage | Error>) {
  let callIndex = 0;

  const getMock = vi.fn().mockImplementation(() => {
    const current = pages[callIndex];
    callIndex++;
    if (current instanceof Error) {
      return Promise.reject(current);
    }
    return Promise.resolve(current);
  });

  const apiMock = vi.fn().mockReturnValue({
    filter: vi.fn().mockReturnThis(),
    select: vi.fn().mockReturnThis(),
    get: getMock,
  });

  return { api: apiMock, _getMock: getMock };
}

function hashEmails(emails: string[]): string {
  return createHash('sha256').update(emails.sort().join(',')).digest('hex');
}

function createMockDb() {
  const deleteMock = vi.fn().mockReturnValue({ where: vi.fn().mockResolvedValue(undefined) });
  const onConflictDoUpdate = vi.fn().mockResolvedValue(undefined);
  const values = vi.fn().mockReturnValue({ onConflictDoUpdate });
  const insertMock = vi.fn().mockReturnValue({ values });
  return { delete: deleteMock, insert: insertMock };
}

function createService(overrides?: {
  config?: Partial<{
    scan: 'disabled' | 'fullAccessOnly' | 'granularAccess';
    sharedMailboxEmails: string[];
    sharedMailboxSyncCronSchedule: string;
  }>;
  factoryResults?: Array<{ client: any; userId: string } | null>;
  cacheResult?: { payload: { envarHash: string; lastSyncedAt: number } } | null;
}) {
  const db = createMockDb();
  const config = {
    scan: 'fullAccessOnly' as const,
    sharedMailboxEmails: [] as string[],
    sharedMailboxSyncCronSchedule: CRON_SCHEDULE,
    ...overrides?.config,
  };

  const factoryResults = overrides?.factoryResults ?? [null];
  const graphClientFactory = {
    createClientForAnyAuthorizedUser: vi.fn(),
  };
  factoryResults.forEach((result, i) => {
    if (i === 0) {
      graphClientFactory.createClientForAnyAuthorizedUser.mockResolvedValueOnce(result);
    } else {
      graphClientFactory.createClientForAnyAuthorizedUser.mockResolvedValueOnce(result);
    }
  });
  // Default to null for any extra calls
  graphClientFactory.createClientForAnyAuthorizedUser.mockResolvedValue(null);

  const cacheResult = overrides?.cacheResult !== undefined ? overrides.cacheResult : null;
  const persistentCacheService = {
    get: vi.fn().mockResolvedValue(cacheResult),
    set: vi.fn().mockResolvedValue(undefined),
  };

  const schedulerRegistry = {
    addCronJob: vi.fn(),
    getCronJob: vi.fn().mockReturnValue({ stop: mockJobStop }),
  };

  const service = new SharedMailboxSyncService(
    db as any,
    config as any,
    graphClientFactory as any,
    persistentCacheService as any,
    schedulerRegistry as any,
  );

  return { service, db, graphClientFactory, persistentCacheService, schedulerRegistry, config };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SharedMailboxSyncService', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  // onModuleInit
  // -------------------------------------------------------------------------

  describe('onModuleInit', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('scan=disabled → returns without running sync or creating cron job', async () => {
      const { service, graphClientFactory, schedulerRegistry } = createService({
        config: { scan: 'disabled' },
      });

      await service.onModuleInit();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).not.toHaveBeenCalled();
      expect(schedulerRegistry.addCronJob).not.toHaveBeenCalled();
    });

    it('cache has matching hash → skips startup sync, still sets up cron', async () => {
      const emails = ['shared@example.com'];
      const matchingHash = hashEmails(emails);
      const { service, graphClientFactory, schedulerRegistry } = createService({
        config: { sharedMailboxEmails: emails },
        cacheResult: { payload: { envarHash: matchingHash, lastSyncedAt: Date.now() } },
      });

      await service.onModuleInit();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).not.toHaveBeenCalled();
      expect(schedulerRegistry.addCronJob).toHaveBeenCalledOnce();
    });

    it('no cache entry → runs startup sync, sets up cron', async () => {
      const mockClient = makeGraphClient([{ value: [] }]);
      const { service, graphClientFactory, schedulerRegistry } = createService({
        config: { sharedMailboxEmails: ['shared@example.com'] },
        cacheResult: null,
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await service.onModuleInit();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledOnce();
      expect(schedulerRegistry.addCronJob).toHaveBeenCalledOnce();
    });

    it('cache has different hash → runs startup sync', async () => {
      const mockClient = makeGraphClient([{ value: [] }]);
      const { service, graphClientFactory } = createService({
        config: { sharedMailboxEmails: ['shared@example.com'] },
        cacheResult: { payload: { envarHash: 'stale-hash', lastSyncedAt: Date.now() } },
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await service.onModuleInit();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledOnce();
    });
  });

  // -------------------------------------------------------------------------
  // onModuleDestroy
  // -------------------------------------------------------------------------

  describe('onModuleDestroy', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('stops the cron job after onModuleInit has been called', async () => {
      const mockClient = makeGraphClient([{ value: [] }]);
      const { service, schedulerRegistry } = createService({
        cacheResult: null,
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await service.onModuleInit();
      service.onModuleDestroy();

      expect(schedulerRegistry.getCronJob).toHaveBeenCalledWith('shared-mailbox-sync');
      expect(mockJobStop).toHaveBeenCalledOnce();
    });

    it('does not throw if schedulerRegistry.getCronJob throws', () => {
      const { service, schedulerRegistry } = createService();
      schedulerRegistry.getCronJob.mockImplementation(() => {
        throw new Error('Job not found');
      });

      expect(() => service.onModuleDestroy()).not.toThrow();
    });
  });

  // -------------------------------------------------------------------------
  // syncIsRunning guard
  // -------------------------------------------------------------------------

  describe('syncIsRunning guard', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('concurrent calls are deduplicated — factory called only once', async () => {
      let resolveFactory!: (value: null) => void;
      const delayedFactory = new Promise<null>((resolve) => {
        resolveFactory = resolve;
      });

      const { service, graphClientFactory } = createService({ cacheResult: null });
      graphClientFactory.createClientForAnyAuthorizedUser.mockReturnValue(delayedFactory);

      const first = (service as any).runSyncWithRetries();
      const second = (service as any).runSyncWithRetries();

      resolveFactory(null);
      await Promise.all([first, second]);

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledOnce();
    });
  });

  // -------------------------------------------------------------------------
  // syncIsRunning try/finally
  // -------------------------------------------------------------------------

  describe('syncIsRunning reset', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('syncIsRunning is reset after a run, allowing a subsequent call to proceed', async () => {
      const mockClient = makeGraphClient([{ value: [] }, { value: [] }]);
      const { service, graphClientFactory } = createService({
        factoryResults: [
          { client: mockClient, userId: 'user1' },
          { client: mockClient, userId: 'user1' },
        ],
      });

      await (service as any).runSyncWithRetries();
      await (service as any).runSyncWithRetries();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledTimes(2);
    });
  });

  // -------------------------------------------------------------------------
  // No authorized user
  // -------------------------------------------------------------------------

  describe('no authorized user', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('returns null from factory → logs warning, no DB operations, no cache update', async () => {
      const { service, db, graphClientFactory, persistentCacheService } = createService({
        config: { sharedMailboxEmails: ['shared@example.com'] },
        factoryResults: [null],
      });

      await (service as any).runSyncWithRetries();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledOnce();
      expect(db.delete).not.toHaveBeenCalled();
      expect(persistentCacheService.set).not.toHaveBeenCalled();
    });
  });

  // -------------------------------------------------------------------------
  // Graph error retry logic
  // -------------------------------------------------------------------------

  describe('Graph error retry logic', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('403 from Graph → excludes userId from next call, retries with another user', async () => {
      const client403 = makeGraphClient([makeGraphError(403)]);
      const clientSuccess = makeGraphClient([{ value: [] }]);

      // Capture snapshots of the excludedIds array at each call time, because
      // the service mutates the same array reference between calls.
      const capturedArgs: string[][] = [];
      // factoryResults: [] keeps the Once queue empty so our mockImplementationOnce
      // calls below are the first entries and aren't shadowed by pre-queued values.
      const { service, graphClientFactory } = createService({
        config: { sharedMailboxEmails: [] },
        factoryResults: [],
      });
      graphClientFactory.createClientForAnyAuthorizedUser
        .mockImplementationOnce((ids: string[]) => {
          capturedArgs.push([...ids]);
          return Promise.resolve({ client: client403, userId: 'user1' });
        })
        .mockImplementationOnce((ids: string[]) => {
          capturedArgs.push([...ids]);
          return Promise.resolve({ client: clientSuccess, userId: 'user2' });
        });

      await (service as any).runSyncWithRetries();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledTimes(2);
      expect(capturedArgs[0]).toEqual([]);
      expect(capturedArgs[1]).toEqual(['user1']);
    });

    it('401 from Graph → excludes userId from next call, retries with another user', async () => {
      const client401 = makeGraphClient([makeGraphError(401)]);
      const clientSuccess = makeGraphClient([{ value: [] }]);

      const { service, graphClientFactory } = createService({
        config: { sharedMailboxEmails: [] },
        factoryResults: [
          { client: client401, userId: 'user1' },
          { client: clientSuccess, userId: 'user2' },
        ],
      });

      await (service as any).runSyncWithRetries();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledTimes(2);
      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenNthCalledWith(2, [
        'user1',
      ]);
    });

    it('429 from Graph → retries with same user (no exclusion)', async () => {
      const client429 = makeGraphClient([makeGraphError(429)]);
      const clientSuccess = makeGraphClient([{ value: [] }]);

      const { service, graphClientFactory } = createService({
        config: { sharedMailboxEmails: [] },
        factoryResults: [
          { client: client429, userId: 'user1' },
          { client: clientSuccess, userId: 'user1' },
        ],
      });

      await (service as any).runSyncWithRetries();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledTimes(2);
      // Both calls exclude nothing extra — excludedUserIds stays empty on 429
      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenNthCalledWith(1, []);
      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenNthCalledWith(2, []);
    });

    it('500 from Graph → retries with same user (transient error)', async () => {
      const client500 = makeGraphClient([makeGraphError(500)]);
      const clientSuccess = makeGraphClient([{ value: [] }]);

      const { service, graphClientFactory } = createService({
        config: { sharedMailboxEmails: [] },
        factoryResults: [
          { client: client500, userId: 'user1' },
          { client: clientSuccess, userId: 'user1' },
        ],
      });

      await (service as any).runSyncWithRetries();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledTimes(2);
      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenNthCalledWith(2, []);
    });

    it('non-retryable GraphError (e.g. 404) → stops after first attempt, no retry', async () => {
      const client404 = makeGraphClient([makeGraphError(404)]);

      const { service, graphClientFactory } = createService({
        config: { sharedMailboxEmails: [] },
        factoryResults: [{ client: client404, userId: 'user1' }],
      });

      await (service as any).runSyncWithRetries();

      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledOnce();
    });

    it('non-FetchUsersError thrown → stops immediately without retry', async () => {
      // Cause an error that is not a GraphError so FetchUsersError wraps a plain Error
      const clientPlainError = makeGraphClient([new Error('unexpected')]);

      const { service, graphClientFactory } = createService({
        config: { sharedMailboxEmails: [] },
        factoryResults: [{ client: clientPlainError, userId: 'user1' }],
      });

      await (service as any).runSyncWithRetries();

      // The error thrown by fetchSharedMailboxCandidatesFromGraph is wrapped in
      // FetchUsersError, but its cause is a plain Error (not GraphError), so
      // handleGraphError returns shouldRetry: false immediately.
      expect(graphClientFactory.createClientForAnyAuthorizedUser).toHaveBeenCalledOnce();
    });
  });

  // -------------------------------------------------------------------------
  // Upsert logic
  // -------------------------------------------------------------------------

  describe('upsert logic', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('matchedUsers empty, envEmails non-empty → delete runs without NOT IN clause, no insert', async () => {
      const mockClient = makeGraphClient([
        { value: [{ id: 'aad-1', mail: 'other@example.com', displayName: 'Other' }] },
      ]);
      const { service, db, persistentCacheService } = createService({
        config: { sharedMailboxEmails: ['shared@example.com'] },
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await (service as any).runSyncWithRetries();

      expect(db.delete).toHaveBeenCalledOnce();
      expect(db.insert).not.toHaveBeenCalled();
      // Cache is still updated even when no users matched
      expect(persistentCacheService.set).toHaveBeenCalledOnce();
    });

    it('matchedUsers non-empty → insert called with correct mapped profile shape', async () => {
      const graphUser = { id: 'aad-id', mail: 'shared@example.com', displayName: 'Shared Mailbox' };
      const mockClient = makeGraphClient([{ value: [graphUser] }]);
      const { service, db } = createService({
        config: { sharedMailboxEmails: ['shared@example.com'] },
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await (service as any).runSyncWithRetries();

      expect(db.insert).toHaveBeenCalledOnce();
      const insertedValues = db.insert.mock.results[0]?.value.values.mock.calls[0][0];
      expect(insertedValues).toHaveLength(1);
      expect(insertedValues[0]).toMatchObject({
        provider: 'microsoft',
        providerUserId: 'aad-id',
        username: 'shared@example.com',
        email: 'shared@example.com',
        displayName: 'Shared Mailbox',
        source: 'shared-mailbox',
        accessToken: null,
      });
    });

    it('email matching is case-insensitive', async () => {
      const graphUser = { id: 'aad-id', mail: 'Shared@Example.COM', displayName: 'Shared Mailbox' };
      const mockClient = makeGraphClient([{ value: [graphUser] }]);
      const { service, db } = createService({
        config: { sharedMailboxEmails: ['shared@example.com'] },
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await (service as any).runSyncWithRetries();

      expect(db.insert).toHaveBeenCalledOnce();
    });

    it('@odata.nextLink pagination → second page merged into results', async () => {
      const user1: GraphUser = {
        id: 'aad-1',
        mail: 'shared1@example.com',
        displayName: 'Mailbox 1',
      };
      const user2: GraphUser = {
        id: 'aad-2',
        mail: 'shared2@example.com',
        displayName: 'Mailbox 2',
      };

      const mockClient = makeGraphClient([
        {
          value: [user1],
          '@odata.nextLink': 'https://graph.microsoft.com/v1.0/users?$skiptoken=abc',
        },
        { value: [user2] },
      ]);

      const { service, db } = createService({
        config: { sharedMailboxEmails: ['shared1@example.com', 'shared2@example.com'] },
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await (service as any).runSyncWithRetries();

      expect(db.insert).toHaveBeenCalledOnce();
      const insertedValues = db.insert.mock.results[0]?.value.values.mock.calls[0][0];
      expect(insertedValues).toHaveLength(2);
      expect(insertedValues.map((v: any) => v.email)).toEqual(
        expect.arrayContaining(['shared1@example.com', 'shared2@example.com']),
      );
    });

    it('cache is updated with new hash after successful sync', async () => {
      const emails = ['shared@example.com'];
      const graphUser = { id: 'aad-id', mail: 'shared@example.com', displayName: 'Shared' };
      const mockClient = makeGraphClient([{ value: [graphUser] }]);
      const { service, persistentCacheService } = createService({
        config: { sharedMailboxEmails: emails },
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await (service as any).runSyncWithRetries();

      expect(persistentCacheService.set).toHaveBeenCalledOnce();
      expect(persistentCacheService.set).toHaveBeenCalledWith(
        SHARED_MAILBOX_SYNC_CACHE_KEY,
        expect.objectContaining({
          dataType: 'SharedMailboxSync',
          payload: expect.objectContaining({
            envarHash: hashEmails(emails),
          }),
        }),
      );
    });
  });

  // -------------------------------------------------------------------------
  // CronJob setup
  // -------------------------------------------------------------------------

  describe('CronJob setup', () => {
    beforeEach(() => {
      vi.clearAllMocks();
    });

    it('setupCronJob registers a job with the configured schedule and calls start()', async () => {
      const { CronJob } = await import('cron');
      const mockClient = makeGraphClient([{ value: [] }]);
      const { service, schedulerRegistry } = createService({
        config: { sharedMailboxSyncCronSchedule: '0 */6 * * *', sharedMailboxEmails: [] },
        cacheResult: null,
        factoryResults: [{ client: mockClient, userId: 'user1' }],
      });

      await service.onModuleInit();

      expect(CronJob).toHaveBeenCalledWith('0 */6 * * *', expect.any(Function));
      expect(schedulerRegistry.addCronJob).toHaveBeenCalledWith(
        'shared-mailbox-sync',
        expect.any(Object),
      );
      expect(mockJobStart).toHaveBeenCalledOnce();
    });
  });
});
