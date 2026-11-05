import { describe, expect, it } from 'vitest';
import { graphMessagePath } from '../graph-message-path';

describe('graphMessagePath', () => {
  it("addresses the message in the signed-in user's own mailbox", () => {
    expect(graphMessagePath({ messageId: 'msg-1' })).toBe('/me/messages/msg-1');
  });

  it('addresses the message in a shared mailbox', () => {
    expect(graphMessagePath({ messageId: 'msg-1', mailbox: 'shared@example.com' })).toBe(
      '/users/shared@example.com/messages/msg-1',
    );
  });

  it('addresses the message through its folder when access is granted per folder', () => {
    expect(
      graphMessagePath({
        messageId: 'AQMk/msg+1=',
        mailbox: 'shared@example.com',
        folderId: 'AQMk/folder+1=',
      }),
    ).toBe('/users/shared@example.com/mailFolders/AQMk-folder+1=/messages/AQMk-msg+1=');
  });

  it('ignores the folder in the own mailbox', () => {
    expect(graphMessagePath({ messageId: 'msg-1', folderId: 'folder-1' })).toBe(
      '/me/messages/msg-1',
    );
  });
});
