/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { GraphError } from '@microsoft/microsoft-graph-client';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { SyncDelegatedAccessCommand } from '../sync-delegated-access.command';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PIPELINE_ID = 'dap_01jxk5r1s2fq9att23mp4z5ef1';
const DELEGATE_USER_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const OWNER_USER_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef3';
const OWNER_EMAIL = 'owner@example.com';
const FOLDER_ID_1 = 'folder-id-1';
const FOLDER_ID_2 = 'folder-id-2';
const FOLDER_ID_3 = 'folder-id-3';

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function makeGraphError(statusCode: number): GraphError {
  const err = new GraphError(statusCode, 'Graph error');
  err.statusCode = statusCode;
  return err;
}

function createMockGraphApi() {
  return {
    select: vi.fn().mockReturnThis(),
    top: vi.fn().mockReturnThis(),
    expand: vi.fn().mockReturnThis(),
    header: vi.fn().mockReturnThis(),
    get: vi.fn(),
  };
}

function createMockGraphClientFactory(graphApi: ReturnType<typeof createMockGraphApi>) {
  return {
    createClientForUser: vi.fn().mockReturnValue({
      api: vi.fn().mockReturnValue(graphApi),
    }),
  };
}

interface DbOptions {
  pipeline?: { delegateUserId: string; ownerUserId: string } | null;
  ownerEmail?: string | null;
  directoryCount?: number;
}

function createMockDb({
  pipeline = { delegateUserId: DELEGATE_USER_ID, ownerUserId: OWNER_USER_ID },
  ownerEmail = OWNER_EMAIL,
  directoryCount = 1,
}: DbOptions = {}) {
  // select chain — returns different values depending on call order
  // 1st call: pipeline lookup
  // 2nd call: owner profile lookup
  // 3rd call: count directories
  const selectResults = [
    pipeline ? [pipeline] : [],
    ownerEmail !== null && ownerEmail !== undefined ? [{ email: ownerEmail }] : [{ email: null }],
    [{ count: directoryCount }],
  ];
  let selectCallIndex = 0;

  const selectWhere = vi.fn().mockImplementation(() => {
    const result = selectResults[selectCallIndex] ?? [];
    selectCallIndex++;
    return Promise.resolve(result);
  });

  const selectFrom = vi.fn().mockReturnValue({ where: selectWhere });
  const select = vi.fn().mockReturnValue({ from: selectFrom });

  // insert chain
  const insertOnConflictDoNothing = vi.fn().mockResolvedValue(undefined);
  const insertValues = vi.fn().mockReturnValue({ onConflictDoNothing: insertOnConflictDoNothing });
  const insert = vi.fn().mockReturnValue({ values: insertValues });

  // delete chain
  const deleteWhere = vi.fn().mockResolvedValue(undefined);
  const deleteFn = vi.fn().mockReturnValue({ where: deleteWhere });

  // update chain
  const updateWhere = vi.fn().mockResolvedValue(undefined);
  const updateSet = vi.fn().mockReturnValue({ where: updateWhere });
  const update = vi.fn().mockReturnValue({ set: updateSet });

  return {
    select,
    insert,
    delete: deleteFn,
    update,
    __select: select,
    __selectWhere: selectWhere,
    __insert: insert,
    __insertValues: insertValues,
    __insertOnConflictDoNothing: insertOnConflictDoNothing,
    __delete: deleteFn,
    __deleteWhere: deleteWhere,
    __update: update,
    __updateSet: updateSet,
    __updateWhere: updateWhere,
  };
}

function createCommand({
  graphApi = createMockGraphApi(),
  db = createMockDb(),
}: {
  graphApi?: ReturnType<typeof createMockGraphApi>;
  db?: ReturnType<typeof createMockDb>;
} = {}): SyncDelegatedAccessCommand {
  return new SyncDelegatedAccessCommand(createMockGraphClientFactory(graphApi) as any, db as any);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SyncDelegatedAccessCommand', () => {
  let graphApi: ReturnType<typeof createMockGraphApi>;

  beforeEach(() => {
    graphApi = createMockGraphApi();
    vi.clearAllMocks();
  });

  it('returns early without any DB writes when pipeline is not found', async () => {
    const db = createMockDb({ pipeline: null });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    expect(graphApi.get).not.toHaveBeenCalled();
    expect(db.__insert).not.toHaveBeenCalled();
    expect(db.__delete).not.toHaveBeenCalled();
    expect(db.__update).not.toHaveBeenCalled();
  });

  it('upserts directory row when message fetch returns 200 for an accessible folder', async () => {
    // preliminary full-access check → 403 (not full access), then folder list, then per-folder messages
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] }) // mailFolders
      .mockResolvedValueOnce({ value: [] }); // messages (200, empty)

    const db = createMockDb({ directoryCount: 1 });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    expect(db.__insert).toHaveBeenCalledOnce();
    expect(db.__insertValues).toHaveBeenCalledWith(
      expect.arrayContaining([
        expect.objectContaining({ pipelineId: PIPELINE_ID, directoryId: FOLDER_ID_1 }),
      ]),
    );
    expect(db.__insertOnConflictDoNothing).toHaveBeenCalledOnce();
  });

  it('deletes directory row on 403 response from message fetch', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] })
      .mockRejectedValueOnce(makeGraphError(403));

    const db = createMockDb({ directoryCount: 0 });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    expect(db.__delete).toHaveBeenCalledWith(expect.anything()); // directories delete
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('deletes directory row on 404 response from message fetch', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] })
      .mockRejectedValueOnce(makeGraphError(404));

    const db = createMockDb({ directoryCount: 0 });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    expect(db.__delete).toHaveBeenCalledWith(expect.anything());
    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('skips folder on 429 — no upsert, throws transient error', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] })
      .mockRejectedValueOnce(makeGraphError(429));

    const db = createMockDb({ directoryCount: 1 });
    const command = createCommand({ graphApi, db });

    await expect(command.run({ pipelineId: PIPELINE_ID })).rejects.toThrow();

    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('skips folder on 5xx — no upsert, throws transient error', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] })
      .mockRejectedValueOnce(makeGraphError(503));

    const db = createMockDb({ directoryCount: 1 });
    const command = createCommand({ graphApi, db });

    await expect(command.run({ pipelineId: PIPELINE_ID })).rejects.toThrow();

    expect(db.__insert).not.toHaveBeenCalled();
  });

  it('does NOT update lastVerifiedAt when a 429 transient error occurred on any folder', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }, { id: FOLDER_ID_2 }] })
      .mockResolvedValueOnce({ value: [] }) // FOLDER_ID_1 succeeds
      .mockRejectedValueOnce(makeGraphError(429)); // FOLDER_ID_2 rate limited

    const db = createMockDb({ directoryCount: 1 });
    const command = createCommand({ graphApi, db });

    await expect(command.run({ pipelineId: PIPELINE_ID })).rejects.toThrow();

    expect(db.__updateSet).not.toHaveBeenCalledWith(
      expect.objectContaining({ lastVerifiedAt: expect.any(Date) }),
    );
  });

  it('does NOT update lastVerifiedAt when a 5xx transient error occurred on any folder', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }, { id: FOLDER_ID_2 }] })
      .mockResolvedValueOnce({ value: [] }) // FOLDER_ID_1 succeeds
      .mockRejectedValueOnce(makeGraphError(500)); // FOLDER_ID_2 transient

    const db = createMockDb({ directoryCount: 1 });
    const command = createCommand({ graphApi, db });

    await expect(command.run({ pipelineId: PIPELINE_ID })).rejects.toThrow();

    expect(db.__updateSet).not.toHaveBeenCalledWith(
      expect.objectContaining({ lastVerifiedAt: expect.any(Date) }),
    );
  });

  it('deletes pipeline row when zero directory rows remain after processing all folders', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] })
      .mockRejectedValueOnce(makeGraphError(403));

    const db = createMockDb({ directoryCount: 0 });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    // The last delete call should be for the pipeline row
    const deleteCalls = db.__delete.mock.calls;
    expect(deleteCalls.length).toBeGreaterThanOrEqual(1);
    // lastVerifiedAt is NOT updated — pipeline was deleted instead
    expect(db.__updateSet).not.toHaveBeenCalledWith(
      expect.objectContaining({ lastVerifiedAt: expect.any(Date) }),
    );
  });

  it('does NOT delete pipeline row when dirCount is 0 but a transient 5xx error occurred', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] })
      .mockRejectedValueOnce(makeGraphError(503));

    const db = createMockDb({ directoryCount: 0 });
    const command = createCommand({ graphApi, db });

    await expect(command.run({ pipelineId: PIPELINE_ID })).rejects.toThrow();

    // Only the directory delete is called, not the pipeline delete
    expect(db.__delete).toHaveBeenCalledOnce();
    expect(db.__updateSet).not.toHaveBeenCalledWith(
      expect.objectContaining({ lastVerifiedAt: expect.any(Date) }),
    );
  });

  it('does NOT delete pipeline row when at least one directory row exists, and updates lastVerifiedAt', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }] })
      .mockResolvedValueOnce({ value: [{ id: 'msg-1' }] });

    const db = createMockDb({ directoryCount: 1 });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    // update is called twice: once for hasFullDelegatedAccess:false, once for lastVerifiedAt
    expect(db.__update).toHaveBeenCalledTimes(2);
    expect(db.__updateSet).toHaveBeenCalledWith(
      expect.objectContaining({ lastVerifiedAt: expect.any(Date) }),
    );
  });

  it('processes multiple folders — upserts accessible ones, deletes inaccessible ones', async () => {
    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({
        value: [{ id: FOLDER_ID_1 }, { id: FOLDER_ID_2 }, { id: FOLDER_ID_3 }],
      })
      .mockResolvedValueOnce({ value: [] }) // FOLDER_ID_1: 200
      .mockRejectedValueOnce(makeGraphError(403)) // FOLDER_ID_2: 403
      .mockResolvedValueOnce({ value: [] }); // FOLDER_ID_3: 200

    const db = createMockDb({ directoryCount: 2 });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    expect(db.__insert).toHaveBeenCalledOnce(); // batch insert of FOLDER_ID_1 and FOLDER_ID_3
    expect(db.__delete).toHaveBeenCalledOnce(); // directories delete
    // update called twice: hasFullDelegatedAccess:false + lastVerifiedAt
    expect(db.__update).toHaveBeenCalledTimes(2);
  });

  it('paginates folder list when @odata.nextLink is present', async () => {
    const nextLinkUrl =
      'https://graph.microsoft.com/v1.0/users/owner@example.com/mailFolders?$skiptoken=abc';

    graphApi.get
      .mockRejectedValueOnce(makeGraphError(403)) // preliminary /messages check
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_1 }], '@odata.nextLink': nextLinkUrl })
      .mockResolvedValueOnce({ value: [{ id: FOLDER_ID_2 }] }) // next page (no nextLink)
      .mockResolvedValueOnce({ value: [] }) // FOLDER_ID_1 messages
      .mockResolvedValueOnce({ value: [] }); // FOLDER_ID_2 messages

    const db = createMockDb({ directoryCount: 2 });
    const command = createCommand({ graphApi, db });

    await command.run({ pipelineId: PIPELINE_ID });

    expect(db.__insert).toHaveBeenCalledOnce();
  });
});
