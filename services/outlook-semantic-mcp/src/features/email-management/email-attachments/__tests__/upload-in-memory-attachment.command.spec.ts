import { ProxyService } from '@unique-ag/proxy';
import { createSmeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { describe, expect, it, vi } from 'vitest';
import { UploadInMemoryAttachmentCommand } from '../upload-in-memory-attachment.command';

function makeClient() {
  const graphRequest = {
    header: vi.fn().mockReturnThis(),
    post: vi.fn().mockResolvedValue({}),
  };
  const api = vi.fn().mockReturnValue(graphRequest);
  return { client: { api } as unknown as Client, api, graphRequest };
}

const data = Buffer.from('hello');
const baseInput = {
  data,
  fileName: createSmeared('a.txt'),
  totalSize: data.length,
  mimeType: 'text/plain',
  userProfileId: 'user-1',
};

describe('UploadInMemoryAttachmentCommand', () => {
  const command = new UploadInMemoryAttachmentCommand({} as ProxyService);

  it('posts a small file to the draft in the signed-in mailbox', async () => {
    const { client, api, graphRequest } = makeClient();

    await command.run({ ...baseInput, client, draftId: 'draft-1' });

    expect(api).toHaveBeenCalledWith('/me/messages/draft-1/attachments');
    expect(graphRequest.header).not.toHaveBeenCalled();
    expect(graphRequest.post).toHaveBeenCalledWith({
      '@odata.type': '#microsoft.graph.fileAttachment',
      name: 'a.txt',
      contentBytes: data.toString('base64'),
      contentType: 'text/plain',
    });
  });

  it('encodes an immutable draft id and sends the ImmutableId header', async () => {
    const { client, api, graphRequest } = makeClient();

    await command.run({
      ...baseInput,
      client,
      draftId: 'AAk/immutable=',
      idIsImmutable: true,
      mailbox: 'shared@example.com',
    });

    expect(api).toHaveBeenCalledWith(
      '/users/shared@example.com/messages/AAk-immutable=/attachments',
    );
    expect(graphRequest.header).toHaveBeenCalledWith('Prefer', 'IdType="ImmutableId"');
  });
});
