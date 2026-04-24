/** biome-ignore-all lint/suspicious/noExplicitAny: Test mock */
import { describe, expect, it, vi } from 'vitest';
import { DeleteInboxDataListener } from '../delete-inbox-data.listener';
import type { ExecuteInboxDeletionCommand } from '../execute-inbox-deletion.command';

const makeValidPayload = () => ({
  type: 'unique.outlook-semantic-mcp.delete-inbox-data.execute',
  payload: { userProfileId: 'user_profile_01jxk5r1s2fq9att23mp4z5ef2' },
});

describe('DeleteInboxDataListener', () => {
  it('delegates to ExecuteInboxDeletionCommand with the userProfileId', async () => {
    const executeInboxDeletion = { run: vi.fn().mockResolvedValue(undefined) };
    const listener = new DeleteInboxDataListener(
      executeInboxDeletion as unknown as ExecuteInboxDeletionCommand,
    );

    await listener.onDeleteInboxData(makeValidPayload());

    expect(executeInboxDeletion.run).toHaveBeenCalledOnce();
    expect(executeInboxDeletion.run).toHaveBeenCalledWith(
      'user_profile_01jxk5r1s2fq9att23mp4z5ef2',
    );
  });
});
