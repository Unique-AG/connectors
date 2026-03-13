import { and, eq, sql } from 'drizzle-orm';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createMockDrizzleDatabase, MockDrizzleDatabase } from '~/__mocks__';
import { inboxConfiguration } from '~/db';
import { IngestEmailCommand } from './ingest-email.command';
import { IngestEmailFromFullSyncCommand } from './ingest-email-from-full-sync.command';

const makeCommand = (
  db: MockDrizzleDatabase,
  ingestEmailCommand: IngestEmailCommand,
): IngestEmailFromFullSyncCommand => {
  const cmd = new IngestEmailFromFullSyncCommand(
    db as unknown as ConstructorParameters<typeof IngestEmailFromFullSyncCommand>[0],
    ingestEmailCommand,
  );
  return cmd;
};

describe('IngestEmailFromFullSyncCommand', () => {
  let db: MockDrizzleDatabase;
  let ingestEmailCommand: { run: ReturnType<typeof vi.fn> };
  let command: IngestEmailFromFullSyncCommand;

  const payload = { userProfileId: 'user-1', messageId: 'msg-1', fullSyncVersion: 'version-1' };

  beforeEach(() => {
    db = createMockDrizzleDatabase();
    ingestEmailCommand = { run: vi.fn().mockResolvedValue(undefined) };
    command = makeCommand(db, ingestEmailCommand as unknown as IngestEmailCommand);
  });

  it('calls IngestEmailCommand.run with the given payload', async () => {
    await command.run(payload);

    expect(ingestEmailCommand.run).toHaveBeenCalledOnce();
    expect(ingestEmailCommand.run).toHaveBeenCalledWith({
      userProfileId: payload.userProfileId,
      messageId: payload.messageId,
    });
  });

  it('increments messagesProcessed after a successful ingest', async () => {
    await command.run(payload);

    expect(db.update).toHaveBeenCalledOnce();
    const updateBuilder = db.update.mock.results?.[0]?.value;
    expect(updateBuilder).toBeDefined();
    expect(updateBuilder.set).toHaveBeenCalledOnce();
    expect(updateBuilder.set).toHaveBeenCalledWith({
      messagesProcessed: sql`${inboxConfiguration.messagesProcessed} + 1`,
    });
    expect(updateBuilder.where).toHaveBeenCalledOnce();
    expect(updateBuilder.where).toHaveBeenCalledWith(
      and(
        eq(inboxConfiguration.userProfileId, payload.userProfileId),
        eq(inboxConfiguration.fullSyncVersion, payload.fullSyncVersion),
      ),
    );
  });

  it('does NOT increment messagesProcessed when IngestEmailCommand throws', async () => {
    ingestEmailCommand.run.mockRejectedValue(new Error('ingest failed'));

    await expect(command.run(payload)).rejects.toThrow('ingest failed');

    expect(db.update).not.toHaveBeenCalled();
  });
});
