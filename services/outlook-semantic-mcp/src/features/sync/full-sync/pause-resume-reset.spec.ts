/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { FullSyncResetCommand } from './full-sync-reset.command';
import { PauseFullSyncCommand } from './pause-full-sync.command';
import { ResumeFullSyncCommand } from './resume-full-sync.command';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';

// ---------------------------------------------------------------------------
// Mock factories
// ---------------------------------------------------------------------------

function createMockDb({
  rowCount = 0,
  config,
}: {
  rowCount?: number;
  config?: { fullSyncState: string } | undefined;
}) {
  return {
    update: vi.fn().mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: vi.fn().mockResolvedValue({ rowCount }),
        }),
      }),
    }),
    query: {
      inboxConfigurations: {
        findFirst: vi.fn().mockResolvedValue(config),
      },
    },
  };
}

function createMockDbForReset() {
  return {
    update: vi.fn().mockReturnValue({
      set: vi.fn().mockReturnValue({
        where: vi.fn().mockReturnValue({
          execute: vi.fn().mockResolvedValue({ rowCount: 1 }),
        }),
      }),
    }),
  };
}

function createMockAmqp() {
  return { publish: vi.fn().mockResolvedValue(undefined) };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('PauseFullSyncCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('pauses sync when in a pausable state', async () => {
    const db = createMockDb({ rowCount: 1 });
    const command = new PauseFullSyncCommand(db as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'paused' });
  });

  it('returns invalid-state when sync is in ready state', async () => {
    const db = createMockDb({
      rowCount: 0,
      config: { fullSyncState: 'ready' },
    });
    const command = new PauseFullSyncCommand(db as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'invalid-state', currentState: 'ready' });
  });

  it('returns invalid-state when sync is in failed state', async () => {
    const db = createMockDb({
      rowCount: 0,
      config: { fullSyncState: 'failed' },
    });
    const command = new PauseFullSyncCommand(db as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'invalid-state', currentState: 'failed' });
  });

  it('returns invalid-state when sync is already paused', async () => {
    const db = createMockDb({
      rowCount: 0,
      config: { fullSyncState: 'paused' },
    });
    const command = new PauseFullSyncCommand(db as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'invalid-state', currentState: 'paused' });
  });

  it('returns not-found when no configuration exists', async () => {
    const db = createMockDb({ rowCount: 0, config: undefined });
    const command = new PauseFullSyncCommand(db as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'not-found' });
  });
});

describe('ResumeFullSyncCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('resumes sync from paused state and publishes retrigger event', async () => {
    const db = createMockDb({ rowCount: 1 });
    const amqp = createMockAmqp();
    const command = new ResumeFullSyncCommand(db as any, amqp as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'resumed' });
    expect(amqp.publish).toHaveBeenCalledOnce();
    expect(amqp.publish).toHaveBeenCalledWith(
      expect.any(String),
      'unique.outlook-semantic-mcp.sync.full-sync',
      expect.objectContaining({
        type: 'unique.outlook-semantic-mcp.sync.full-sync',
        payload: { userProfileId: USER_PROFILE_ID },
      }),
    );
  });

  it('returns invalid-state when sync is running', async () => {
    const db = createMockDb({
      rowCount: 0,
      config: { fullSyncState: 'running' },
    });
    const amqp = createMockAmqp();
    const command = new ResumeFullSyncCommand(db as any, amqp as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'invalid-state', currentState: 'running' });
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('returns invalid-state when sync is in ready state', async () => {
    const db = createMockDb({
      rowCount: 0,
      config: { fullSyncState: 'ready' },
    });
    const amqp = createMockAmqp();
    const command = new ResumeFullSyncCommand(db as any, amqp as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'invalid-state', currentState: 'ready' });
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('returns invalid-state when sync is in failed state', async () => {
    const db = createMockDb({
      rowCount: 0,
      config: { fullSyncState: 'failed' },
    });
    const amqp = createMockAmqp();
    const command = new ResumeFullSyncCommand(db as any, amqp as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'invalid-state', currentState: 'failed' });
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('returns invalid-state when sync is waiting-for-ingestion', async () => {
    const db = createMockDb({
      rowCount: 0,
      config: { fullSyncState: 'waiting-for-ingestion' },
    });
    const amqp = createMockAmqp();
    const command = new ResumeFullSyncCommand(db as any, amqp as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'invalid-state', currentState: 'waiting-for-ingestion' });
    expect(amqp.publish).not.toHaveBeenCalled();
  });

  it('returns not-found when no configuration exists', async () => {
    const db = createMockDb({ rowCount: 0, config: undefined });
    const amqp = createMockAmqp();
    const command = new ResumeFullSyncCommand(db as any, amqp as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result).toEqual({ status: 'not-found' });
    expect(amqp.publish).not.toHaveBeenCalled();
  });
});

describe('FullSyncResetCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('resets state to ready with a new version and zeroed counters', async () => {
    const db = createMockDbForReset();
    const command = new FullSyncResetCommand(db as any);

    const result = await command.run(USER_PROFILE_ID);

    expect(result.version).toBeDefined();
    expect(typeof result.version).toBe('string');
    expect(result.version.length).toBeGreaterThan(0);

    const setCall = db.update.mock?.results?.[0]?.value.set;
    expect(setCall).toHaveBeenCalledWith(
      expect.objectContaining({
        fullSyncVersion: result.version,
        fullSyncNextLink: null,
        fullSyncBatchIndex: 0,
        fullSyncSkipped: 0,
        fullSyncScheduledForIngestion: 0,
        fullSyncFailedToUploadForIngestion: 0,
        fullSyncExpectedTotal: null,
        fullSyncState: 'ready',
      }),
    );
  });

  it('generates a unique version on each call', async () => {
    const db1 = createMockDbForReset();
    const db2 = createMockDbForReset();
    const command1 = new FullSyncResetCommand(db1 as any);
    const command2 = new FullSyncResetCommand(db2 as any);

    const result1 = await command1.run(USER_PROFILE_ID);
    const result2 = await command2.run(USER_PROFILE_ID);

    expect(result1.version).not.toBe(result2.version);
  });
});
