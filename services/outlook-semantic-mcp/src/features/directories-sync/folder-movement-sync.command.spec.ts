/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import Bottleneck from 'bottleneck';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FolderMovementSyncCommand } from './folder-movement-sync.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const FOLDER_ID = 'dir_01jxk5r1s2fq9att23mp4z5ef3';
const PROVIDER_FOLDER_ID = 'AAMk-folder-01';

// A recent heartbeat (within the 20-minute running threshold)
const RECENT_HEARTBEAT = new Date(Date.now() - 1 * 60 * 1000); // 1 minute ago
// A stale heartbeat (well outside the 20-minute threshold)
const STALE_HEARTBEAT = new Date(Date.now() - 999 * 60 * 1000); // ~16 hours ago

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeMessage(id: string) {
  return {
    id,
    createdDateTime: '2024-01-01T00:00:00Z',
    lastModifiedDateTime: '2024-01-01T00:00:00Z',
    receivedDateTime: '2024-01-01T00:00:00Z',
    parentFolderId: PROVIDER_FOLDER_ID,
    webLink: 'https://outlook.office.com/mail/id/123',
  };
}

function makeGraphResponse(messages: ReturnType<typeof makeMessage>[], nextLink?: string) {
  return {
    value: messages,
    ...(nextLink ? { '@odata.nextLink': nextLink } : {}),
  };
}

function makeFolder(overrides: Partial<{
  id: string;
  providerDirectoryId: string;
  directoryMovementResyncCursor: string | null;
}> = {}) {
  return {
    id: FOLDER_ID,
    providerDirectoryId: PROVIDER_FOLDER_ID,
    directoryMovementResyncCursor: null,
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
    top: vi.fn().mockReturnThis(),
    orderby: vi.fn().mockReturnThis(),
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

function createMockIngestEmailCommand() {
  return { run: vi.fn().mockResolvedValue('ingested') };
}

/**
 * Creates a mock DB supporting:
 * - `db.transaction(cb)` — lock acquisition transaction
 * - `db.select().from().where().orderBy().limit().then()` — folder query (returns folders array)
 * - `db.update().set().where().execute()` — folder clear + state transitions
 *
 * `lockRow`: the row returned inside the transaction. Undefined = no row (skips).
 * `folders`: successive calls to select return these folders (one per outer loop iteration).
 */
function createMockDb({
  lockRow,
  folders = [],
}: {
  lockRow?: {
    folderMovementSyncState: string | null;
    folderMovementSyncHeartbeatAt: Date | null;
  };
  folders?: (ReturnType<typeof makeFolder> | undefined)[];
}) {
  // Transaction mock
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
          for: vi.fn().mockReturnValue({
            then: vi.fn((cb: (rows: any[]) => any) => cb(lockRow ? [lockRow] : [])),
          }),
        }),
      }),
    }),
    update: vi.fn().mockReturnValue(txUpdate),
  };

  // Outer select mock — each call returns the next folder in the list
  let folderCallIndex = 0;
  const dbExecuteFn = vi.fn().mockResolvedValue(undefined);
  const dbUpdate = {
    set: vi.fn().mockReturnValue({
      where: vi.fn().mockReturnValue({
        execute: dbExecuteFn,
      }),
    }),
  };

  const db: any = {
    transaction: vi.fn(async (cb: (tx: any) => Promise<any>) => cb(tx)),
    select: vi.fn().mockImplementation(() => ({
      from: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          orderBy: vi.fn().mockReturnValue({
            limit: vi.fn().mockReturnValue({
              then: vi.fn((cb: (rows: any[]) => any) => {
                const folder = folders[folderCallIndex++];
                return cb(folder ? [folder] : []);
              }),
            }),
          }),
        }),
      }),
    })),
    update: vi.fn().mockReturnValue(dbUpdate),
    __tx: tx,
    __txExecuteFn: txExecuteFn,
    __txUpdate: txUpdate,
    __dbExecuteFn: dbExecuteFn,
    __dbUpdate: dbUpdate,
  };

  return db;
}

function createCommand({
  graphApi,
  ingestEmailCommand,
  db,
}: {
  graphApi: ReturnType<typeof createMockGraphApi>;
  ingestEmailCommand: ReturnType<typeof createMockIngestEmailCommand>;
  db: ReturnType<typeof createMockDb>;
}): FolderMovementSyncCommand {
  return new FolderMovementSyncCommand(
    createMockGraphClientFactory(graphApi) as any,
    ingestEmailCommand as any,
    db as any,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FolderMovementSyncCommand', () => {
  let graphApi: ReturnType<typeof createMockGraphApi>;
  let ingestEmailCommand: ReturnType<typeof createMockIngestEmailCommand>;

  beforeEach(() => {
    graphApi = createMockGraphApi();
    ingestEmailCommand = createMockIngestEmailCommand();
    vi.clearAllMocks();
  });

  it('skips when folderMovementSyncState is running with recent heartbeat', async () => {
    const db = createMockDb({
      lockRow: {
        folderMovementSyncState: 'running',
        folderMovementSyncHeartbeatAt: RECENT_HEARTBEAT,
      },
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db });

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toBe('skipped');
    expect(graphApi.get).not.toHaveBeenCalled();
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('proceeds and overrides stale running lock', async () => {
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([]));

    const db = createMockDb({
      lockRow: {
        folderMovementSyncState: 'running',
        folderMovementSyncHeartbeatAt: STALE_HEARTBEAT,
      },
      folders: [undefined], // no marked folders found
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db });

    const result = await command.run(USER_PROFILE_ID);

    // Lock was overridden (tx update called to set 'running')
    expect(db.__txUpdate.set).toHaveBeenCalledWith(
      expect.objectContaining({ folderMovementSyncState: 'running' }),
    );
    // Proceeded to processing (state set to 'ready' afterward)
    expect(result).toBe('completed');
    expect(ingestEmailCommand.run).not.toHaveBeenCalled();
  });

  it('processes messages in a folder with no nextLink and sets state to ready', async () => {
    const messages = Array.from({ length: 50 }, (_, i) => makeMessage(`msg-${i}`));
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(messages));

    const folder = makeFolder();
    const db = createMockDb({
      lockRow: { folderMovementSyncState: null, folderMovementSyncHeartbeatAt: null },
      folders: [folder, undefined],
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db });

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toBe('completed');
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(50);

    // Folder markers cleared
    expect(db.__dbUpdate.set).toHaveBeenCalledWith(
      expect.objectContaining({ parentChangeDetectedAt: null, directoryMovementResyncCursor: null }),
    );

    // Final state set to 'ready'
    expect(db.update).toHaveBeenCalled();
    const allSetCalls: any[] = db.__dbUpdate.set.mock.calls.map((c: any[]) => c[0]);
    expect(allSetCalls.some((s) => s.folderMovementSyncState === 'ready')).toBe(true);
  });

  it('stores cursor and stops loop when processed count reaches 100', async () => {
    const NEXT_LINK = 'https://graph.microsoft.com/v1.0/nextPage';
    const firstPage = Array.from({ length: 100 }, (_, i) => makeMessage(`msg-${i}`));

    graphApi.get.mockResolvedValueOnce(makeGraphResponse(firstPage, NEXT_LINK));

    const folder = makeFolder();
    const db = createMockDb({
      lockRow: { folderMovementSyncState: null, folderMovementSyncHeartbeatAt: null },
      folders: [folder],
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db });

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toBe('completed');
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(100);

    // Cursor stored, markers NOT cleared
    const allSetCalls: any[] = db.__dbUpdate.set.mock.calls.map((c: any[]) => c[0]);
    expect(allSetCalls.some((s) => s.directoryMovementResyncCursor === NEXT_LINK)).toBe(true);
    expect(allSetCalls.some((s) => s.parentChangeDetectedAt === null)).toBe(false);

    // Graph was only called once (loop stopped after threshold)
    expect(graphApi.get).toHaveBeenCalledTimes(1);
  });

  it('resumes from cursor on second invocation', async () => {
    const CURSOR = 'https://graph.microsoft.com/v1.0/nextPage';
    const secondPage = Array.from({ length: 50 }, (_, i) => makeMessage(`msg2-${i}`));

    graphApi.get.mockResolvedValueOnce(makeGraphResponse(secondPage));

    const folderWithCursor = makeFolder({ directoryMovementResyncCursor: CURSOR });
    const db = createMockDb({
      lockRow: { folderMovementSyncState: null, folderMovementSyncHeartbeatAt: null },
      folders: [folderWithCursor, undefined],
    });
    const graphClientFactory = createMockGraphClientFactory(graphApi);
    const command = new FolderMovementSyncCommand(
      graphClientFactory as any,
      ingestEmailCommand as any,
      db as any,
    );

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toBe('completed');

    // api() was called with the cursor URL
    const client = graphClientFactory.createClientForUser.mock.results[0].value;
    expect(client.api).toHaveBeenCalledWith(CURSOR);

    // Folder markers cleared after exhausting the page
    const allSetCalls: any[] = db.__dbUpdate.set.mock.calls.map((c: any[]) => c[0]);
    expect(allSetCalls.some((s) => s.parentChangeDetectedAt === null)).toBe(true);
  });

  it('sets state to failed when ingestEmailCommand.run throws a non-rate-limit error', async () => {
    const folder = makeFolder();
    const db = createMockDb({
      lockRow: { folderMovementSyncState: null, folderMovementSyncHeartbeatAt: null },
      folders: [folder],
    });

    // Make graph api return one message, and ingest throws
    graphApi.get.mockResolvedValueOnce(makeGraphResponse([makeMessage('msg-err')]));
    ingestEmailCommand.run.mockRejectedValueOnce(new Error('unexpected error'));

    const command = createCommand({ graphApi, ingestEmailCommand, db });

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toBe('failed');
    const allSetCalls: any[] = db.__dbUpdate.set.mock.calls.map((c: any[]) => c[0]);
    expect(allSetCalls.some((s) => s.folderMovementSyncState === 'failed')).toBe(true);
  });

  it('rethrows rate limit errors from ingestEmailCommand.run', async () => {
    const folder = makeFolder();
    const db = createMockDb({
      lockRow: { folderMovementSyncState: null, folderMovementSyncHeartbeatAt: null },
      folders: [folder],
    });

    graphApi.get.mockResolvedValueOnce(makeGraphResponse([makeMessage('msg-rl')]));
    const rateLimitError = new Bottleneck.BottleneckError('rate limited');
    ingestEmailCommand.run.mockRejectedValueOnce(rateLimitError);

    const command = createCommand({ graphApi, ingestEmailCommand, db });

    await expect(command.run(USER_PROFILE_ID)).rejects.toThrow(Bottleneck.BottleneckError);
  });

  it('logs and continues when ingestEmailCommand.run returns failed', async () => {
    const messages = [makeMessage('msg-a'), makeMessage('msg-b')];
    graphApi.get.mockResolvedValueOnce(makeGraphResponse(messages));

    ingestEmailCommand.run
      .mockResolvedValueOnce('failed')
      .mockResolvedValueOnce('ingested');

    const folder = makeFolder();
    const db = createMockDb({
      lockRow: { folderMovementSyncState: null, folderMovementSyncHeartbeatAt: null },
      folders: [folder, undefined],
    });
    const command = createCommand({ graphApi, ingestEmailCommand, db });

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toBe('completed');
    // Both messages were attempted despite the first returning 'failed'
    expect(ingestEmailCommand.run).toHaveBeenCalledTimes(2);
  });
});
