import { UniqueApiClient, UniqueOwnerType } from '@unique-ag/unique-api';
import { Smeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { UniqueConfigNamespaced } from '~/config';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import {
  AttachmentUploadResult,
  ResolvedUniqueIdentity,
  UPLOAD_CHUNK_SIZE,
  UploadSessionSchema,
} from './utils';

@Injectable()
export class StreamUniqueAttachmentCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly configService: ConfigService<UniqueConfigNamespaced, true>,
    @InjectUniqueApi() private readonly uniqueApiClient: UniqueApiClient,
  ) {}

  public async run({
    client,
    draftId,
    fileInfo: { contentId, fileName },
    uniqueIdentity,
    userProfileId,
  }: {
    client: Client;
    draftId: string;
    fileInfo: {
      contentId: string;
      fileName: Smeared;
    };
    uniqueIdentity: ResolvedUniqueIdentity;
    userProfileId: string;
  }): Promise<AttachmentUploadResult> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    if (uniqueConfig.serviceAuthMode !== 'cluster_local') {
      return {
        status: 'failed',
        reason: { fileName: fileName.value, reason: 'App is not running in cluster local' },
      };
    }
    if (!uniqueIdentity) {
      return {
        status: 'failed',
        reason: { fileName: fileName.value, reason: 'Could not resolve unique identity' },
      };
    }

    const content = await this.uniqueApiClient.content.getContentById({ contentId });
    const chatId = content.ownerType === UniqueOwnerType.Chat ? content.ownerId : undefined;

    // We impersonate the Unique user so the content API authorizes
    // the download as if the user themselves initiated it.
    const contentUrl = new URL(
      `${uniqueConfig.ingestionServiceBaseUrl}/v1/content/${encodeURIComponent(contentId)}/file`,
    );
    if (chatId) {
      contentUrl.searchParams.set('chatId', chatId);
    }

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
          fileName: fileName.value,
          reason: `Unique content download failed (${response.status}): ${text}`,
        },
      };
    }

    const totalSize = Number(response.headers.get('content-length'));
    if (!totalSize || !response.body) {
      await response.body?.cancel();
      return {
        status: 'failed',
        reason: {
          fileName: fileName.value,
          reason: 'Missing content-length header or empty body from content service',
        },
      };
    }

    const mimeType = response.headers.get('content-type');

    const totalChunks = Math.ceil(totalSize / UPLOAD_CHUNK_SIZE);
    this.logger.log({
      msg: 'Uploading unique attachment via streamed upload session',
      userProfileId,
      draftId,
      fileName,
      sizeBytes: totalSize,
      totalChunks,
    });

    const reader = response.body.getReader();

    try {
      await this.streamToUploadSession({
        reader,
        client,
        draftId,
        fileName,
        mimeType,
        totalSize,
        totalChunks,
        userProfileId,
      });
    } finally {
      reader.cancel();
    }

    return { status: 'success' };
  }

  private async streamToUploadSession({
    reader,
    client,
    draftId,
    fileName,
    mimeType,
    totalSize,
    totalChunks,
    userProfileId,
  }: {
    reader: ReadableStreamDefaultReader<Uint8Array<ArrayBufferLike>>;
    client: Client;
    draftId: string;
    fileName: Smeared;
    mimeType: string | null;
    totalSize: number;
    totalChunks: number;
    userProfileId: string;
  }): Promise<void> {
    let offset = 0;
    let chunkIndex = 0;
    let pending = Buffer.alloc(0);

    const { uploadUrl } = UploadSessionSchema.parse(
      await client.api(`/me/messages/${draftId}/attachments/createUploadSession`).post({
        AttachmentItem: {
          attachmentType: 'file',
          name: fileName.value,
          size: totalSize,
          ...(mimeType ? { contentType: mimeType } : {}),
        },
      }),
    );

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
            msg: `${chunkIndex}/${totalChunks} chunks uploaded`,
            userProfileId,
            draftId,
            fileName,
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
          msg: 'Upload finished',
          userProfileId,
          draftId,
          fileName,
          chunkIndex,
          totalChunks,
          bytesUploaded: offset,
          totalBytes: totalSize,
        });
        break;
      }
    }
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
        // The content type on each chunk is octet-stream not the actual mime type of the file.
        'Content-Type': 'application/octet-stream',
      },
      body: chunk as BodyInit,
    });
    // 308 (Resume Incomplete) is the expected response for intermediate chunks;
    // only the final chunk returns 200/201.
    if (!response.ok && response.status !== 308) {
      const text = await response.text();
      throw new Error(`Upload session chunk failed (${response.status}): ${text}`);
    }
    await response.body?.cancel();
  }
}
