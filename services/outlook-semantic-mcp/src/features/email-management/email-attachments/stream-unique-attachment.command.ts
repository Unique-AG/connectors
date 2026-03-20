import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { createSmeared } from '@unique-ag/utils/src/smeared';
import { UniqueConfigNamespaced } from '~/config';
import {
  AttachmentUploadResult,
  ResolvedUniqueIdentity,
  UPLOAD_CHUNK_SIZE,
  UploadSessionSchema,
} from './utils';

@Injectable()
export class StreamUniqueAttachmentCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly configService: ConfigService<UniqueConfigNamespaced, true>) {}

  public async run({
    client,
    draftId,
    fileInfo: { chatId, contentId, fileName },
    uniqueIdentity,
    userProfileId,
  }: {
    client: Client;
    draftId: string;
    fileInfo: {
      chatId: string | null | undefined;
      contentId: string;
      fileName: string;
    };
    uniqueIdentity: ResolvedUniqueIdentity;
    userProfileId: string;
  }): Promise<AttachmentUploadResult> {
    if (!chatId) {
      return {
        status: 'failed',
        reason: { fileName, reason: 'Missing chatId for unique:// attachment' },
      };
    }

    const uniqueConfig = this.configService.get('unique', { infer: true });
    if (uniqueConfig.serviceAuthMode !== 'cluster_local') {
      return {
        status: 'failed',
        reason: { fileName, reason: 'App is not running in cluster local' },
      };
    }
    if (!uniqueIdentity) {
      return {
        status: 'failed',
        reason: { fileName, reason: 'Could not resolve unique identity' },
      };
    }

    // We impersonate the Unique user so the content API authorizes
    // the download as if the user themselves initiated it.
    const contentUrl = new URL(
      `${uniqueConfig.ingestionServiceBaseUrl}/v1/content/${encodeURIComponent(contentId)}/file`,
    );
    contentUrl.searchParams.set('chatId', chatId);

    const response = await fetch(contentUrl, {
      headers: {
        'x-user-id': uniqueIdentity.userId,
        'x-company-id': uniqueIdentity.companyId,
        'x-service-id': 'outlook-semantic-mcp',
      },
    });

    if (!response.ok) {
      const text = await response.text();
      return {
        status: 'failed',
        reason: {
          fileName,
          reason: `Unique content download failed (${response.status}): ${text}`,
        },
      };
    }

    const totalSize = Number(response.headers.get('content-length'));
    if (!totalSize || !response.body) {
      return {
        status: 'failed',
        reason: {
          fileName,
          reason: 'Missing content-length header or empty body from content service',
        },
      };
    }

    const totalChunks = Math.ceil(totalSize / UPLOAD_CHUNK_SIZE);
    this.logger.log({
      msg: 'Uploading unique attachment via streamed upload session',
      userProfileId,
      draftId,
      filename: createSmeared(fileName),
      sizeBytes: totalSize,
      totalChunks,
    });

    const { uploadUrl } = UploadSessionSchema.parse(
      await client.api(`/me/messages/${draftId}/attachments/createUploadSession`).post({
        AttachmentItem: { attachmentType: 'file', name: fileName, size: totalSize },
      }),
    );

    const reader = response.body.getReader();
    let offset = 0;
    let chunkIndex = 0;
    let pending = Buffer.alloc(0);

    while (true) {
      const { done, value } = await reader.read();

      if (value) {
        pending = Buffer.concat([pending, Buffer.from(value)]);
      }

      while (pending.length >= UPLOAD_CHUNK_SIZE) {
        const chunk = pending.subarray(0, UPLOAD_CHUNK_SIZE);
        pending = pending.subarray(UPLOAD_CHUNK_SIZE);
        const end = Math.min(offset + UPLOAD_CHUNK_SIZE, totalSize);
        await this.uploadChunk(uploadUrl, chunk, offset, end, totalSize);
        chunkIndex++;

        if (chunkIndex % 20 === 0) {
          this.logger.log({
            msg: 'Chunk uploaded',
            userProfileId,
            draftId,
            filename: createSmeared(fileName),
            chunkIndex,
            totalChunks,
            bytesUploaded: end,
            totalBytes: totalSize,
          });
        }
        offset = end;
      }

      if (done) {
        if (pending.length > 0) {
          const end = offset + pending.length;
          await this.uploadChunk(uploadUrl, pending, offset, end, totalSize);
          offset += pending.length;
          chunkIndex++;
        }
        this.logger.log({
          msg: 'Upload finished uploaded',
          userProfileId,
          draftId,
          filename: createSmeared(fileName),
          chunkIndex,
          totalChunks,
          bytesUploaded: offset,
          totalBytes: totalSize,
        });
        break;
      }
    }

    return { status: 'success' };
  }

  private async uploadChunk(
    uploadUrl: string,
    chunk: Buffer,
    offset: number,
    end: number,
    totalSize: number,
  ): Promise<void> {
    const response = await fetch(uploadUrl, {
      method: 'PUT',
      headers: {
        'Content-Length': String(chunk.length),
        'Content-Range': `bytes ${offset}-${end - 1}/${totalSize}`,
        // The content type on each chunk is octet-stream the mime type of the file was already declared.
        'Content-Type': 'application/octet-stream',
      },
      body: chunk as BodyInit,
    });
    if (!response.ok && response.status !== 308) {
      const text = await response.text();
      throw new Error(`Upload session chunk failed (${response.status}): ${text}`);
    }
    await response.body?.cancel();
  }
}
