import { describe, expect, it } from 'vitest';
import { getMetadataFromMessage } from './get-metadata-from-message';

describe('getMetadataFromMessage', () => {
  it('includes emailProviderFolderPath from the folderPath argument', () => {
    const message = { id: 'msg-1' };
    const result = getMetadataFromMessage(message as never, 'Inbox/Subfolder');
    expect(result.emailProviderFolderPath).toBe('Inbox/Subfolder');
  });
});
