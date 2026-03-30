/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import Bottleneck from 'bottleneck';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { IngestEmailCommand } from './ingest-email.command';

vi.mock('~/features/tracing.utils', () => ({
  traceAttrs: vi.fn(),
  traceEvent: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const USER_PROFILE_ID = 'user_profile_01jxk5r1s2fq9att23mp4z5ef2';
const MESSAGE_ID = 'message_01jxk5r1s2fq9att23mp4z5ef2';

function createCommand() {
  // Construct with all dependencies as undefined — ingestEmail is spied out, so they are never used.
  const command = new IngestEmailCommand(
    undefined as any,
    undefined as any,
    undefined as any,
    undefined as any,
    undefined as any,
    undefined as any,
    undefined as any,
  );
  vi.spyOn(command as any, 'sleep').mockResolvedValue(undefined);
  return command;
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('IngestEmailCommand retry logic', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('calls ingestEmail up to 3 times on repeated failure and returns failed', async () => {
    const command = createCommand();
    vi.spyOn(command as any, 'ingestEmail').mockRejectedValue(new Error('transient error'));

    const result = await command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID });

    expect(result).toBe('failed');
    expect((command as any).ingestEmail).toHaveBeenCalledTimes(3);
  });

  it('returns the result immediately on first success', async () => {
    const command = createCommand();
    vi.spyOn(command as any, 'ingestEmail').mockResolvedValue('ingested');

    const result = await command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID });

    expect(result).toBe('ingested');
    expect((command as any).ingestEmail).toHaveBeenCalledTimes(1);
  });

  it('returns the result on second attempt after one failure', async () => {
    const command = createCommand();
    vi.spyOn(command as any, 'ingestEmail')
      .mockRejectedValueOnce(new Error('transient error'))
      .mockResolvedValueOnce('metadata-updated');

    const result = await command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID });

    expect(result).toBe('metadata-updated');
    expect((command as any).ingestEmail).toHaveBeenCalledTimes(2);
  });

  it('re-throws BottleneckError immediately without retrying', async () => {
    const command = createCommand();
    const bottleneckError = new Bottleneck.BottleneckError('rate limiter stopped');
    vi.spyOn(command as any, 'ingestEmail').mockRejectedValue(bottleneckError);

    await expect(
      command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID }),
    ).rejects.toThrow(Bottleneck.BottleneckError);

    expect((command as any).ingestEmail).toHaveBeenCalledTimes(1);
  });

  it('applies exponential backoff between retry attempts', async () => {
    const command = createCommand();
    vi.spyOn(command as any, 'ingestEmail').mockRejectedValue(new Error('transient error'));
    const sleepSpy = vi.spyOn(command as any, 'sleep').mockResolvedValue(undefined);

    await command.run({ userProfileId: USER_PROFILE_ID, messageId: MESSAGE_ID });

    // sleep is called between attempt 1→2 (500ms) and attempt 2→3 (1000ms), not after attempt 3
    expect(sleepSpy).toHaveBeenCalledTimes(2);
    expect(sleepSpy).toHaveBeenNthCalledWith(1, 500); // 500 * 2^0
    expect(sleepSpy).toHaveBeenNthCalledWith(2, 1000); // 500 * 2^1
  });
});
