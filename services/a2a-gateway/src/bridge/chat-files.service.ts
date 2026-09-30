import { Inject, Injectable } from '@nestjs/common';
import { z } from 'zod';
import type { RequestIdentity } from '../auth/identity.guard.js';
import { GATEWAY_CONFIG, type GatewayConfig } from '../config/config.js';
import { UniqueInternalClient } from '../unique/unique-internal.client.js';
import { UniqueInternalError } from '../unique/unique-internal.error.js';

const createdContent = z.object({
  id: z.string(),
  writeUrl: z.string().url(),
  readUrl: z.string().min(1),
});

export interface ChatFile {
  bytes: Buffer;
  mimeType: string;
  filename: string;
}

/** Uploads to and downloads from a chat under the effective user's own content permissions. */
@Injectable()
export class ChatFilesService {
  public constructor(
    private readonly unique: UniqueInternalClient,
    @Inject(GATEWAY_CONFIG) private readonly config: GatewayConfig,
  ) {}

  public async upload(identity: RequestIdentity, chatId: string, file: ChatFile): Promise<string> {
    const input = {
      key: file.filename,
      title: file.filename,
      mimeType: file.mimeType,
      ownerType: 'CHAT',
    };
    const content = createdContent.parse(
      await this.unique.upsertChatContent(identity, chatId, input),
    );
    let response: Response;
    try {
      // The write URL is the platform's own blob storage, issued by ingestion for this upload.
      response = await fetch(content.writeUrl, {
        method: 'PUT',
        body: new Uint8Array(file.bytes),
        headers: {
          'x-ms-blob-type': 'BlockBlob',
          'x-ms-blob-content-type': file.mimeType,
          'content-type': file.mimeType,
        },
        redirect: 'error',
        signal: AbortSignal.timeout(this.config.streamTimeoutMs),
      });
    } catch {
      throw new UniqueInternalError('chat file upload failed', 'UNAVAILABLE', true);
    }
    if (!response.ok) {
      throw new UniqueInternalError(
        `chat file upload returned ${response.status}`,
        'UNAVAILABLE',
        true,
      );
    }
    await this.unique.upsertChatContent(
      identity,
      chatId,
      { ...input, byteSize: file.bytes.byteLength },
      content.readUrl,
    );
    return content.id;
  }

  public download(identity: RequestIdentity, chatId: string, contentId: string): Promise<ChatFile> {
    return this.unique.downloadContent(identity, contentId, chatId, this.config.maxRemoteFileBytes);
  }
}
