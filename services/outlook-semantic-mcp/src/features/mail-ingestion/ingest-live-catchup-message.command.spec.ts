/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestEmailLiveCatchupMessageCommand } from './ingest-live-catchup-message.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
}));

const SUBSCRIPTION_ID = 'sub_01jxk5r1s2fq9att23mp4z5ef2';
const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const MESSAGE_ID = 'message_01jxk5r1s2fq9att23mp4z5ef2';

function createCommand(ingestResult: string) {
  const db = {
    query: {
      subscriptions: {
        findFirst: vi.fn().mockResolvedValue({ userProfileId: USER_PROFILE_ID }),
      },
      inboxConfigurations: {
        findFirst: vi.fn().mockResolvedValue(null),
      },
    },
  };

  const ingestEmailCommand = {
    run: vi.fn().mockResolvedValue(ingestResult),
  };

  const command = new IngestEmailLiveCatchupMessageCommand(db as any, ingestEmailCommand as any);

  return { command, ingestEmailCommand };
}

describe('IngestEmailLiveCatchupMessageCommand', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('throws when ingestEmailCommand returns failed', async () => {
    const { command } = createCommand('failed');

    await expect(
      command.run({ subscriptionId: SUBSCRIPTION_ID, messageId: MESSAGE_ID }),
    ).rejects.toThrow();
  });

  it('resolves without throwing when ingestion succeeds', async () => {
    const { command } = createCommand('ingested');

    await expect(
      command.run({ subscriptionId: SUBSCRIPTION_ID, messageId: MESSAGE_ID }),
    ).resolves.toBeUndefined();
  });

  it('resolves without throwing when email is skipped', async () => {
    const { command } = createCommand('skipped');

    await expect(
      command.run({ subscriptionId: SUBSCRIPTION_ID, messageId: MESSAGE_ID }),
    ).resolves.toBeUndefined();
  });
});
