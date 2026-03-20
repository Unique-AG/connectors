import { createSmeared } from '@unique-ag/utils';
import { Client } from '@microsoft/microsoft-graph-client';
import { Injectable, Logger } from '@nestjs/common';
import { AttachmentUploadResult, UPLOAD_CHUNK_SIZE, UploadSessionSchema } from './utils';

@Injectable()
export class UploadInMemoryAttachmentCommand {
  public logger = new Logger(this.constructor.name);

  public async run({
    client,
    draftId,
    data,
    filename,
    totalSize,
    userProfileId,
  }: {
    client: Client;
    draftId: string;
    data: Buffer;
    filename: string;
    totalSize: number;
    userProfileId: string;
  }): Promise<AttachmentUploadResult> {
    if (totalSize <= 3 * 1024 * 1024) {
      this.logger.log({
        msg: 'Uploading attachment via simple POST',
        userProfileId,
        draftId,
        filename: createSmeared(filename),
        sizeBytes: totalSize,
      });
      await client.api(`/me/messages/${draftId}/attachments`).post({
        '@odata.type': '#microsoft.graph.fileAttachment',
        name: filename,
        contentBytes: data.toString('base64'),
      });
      return { status: 'success' };
    }

    const totalChunks = Math.ceil(totalSize / UPLOAD_CHUNK_SIZE);
    this.logger.log({
      msg: 'Uploading attachment via upload session',
      userProfileId,
      draftId,
      filename: createSmeared(filename),
      sizeBytes: totalSize,
      totalChunks,
    });

    const { uploadUrl } = UploadSessionSchema.parse(
      await client.api(`/me/messages/${draftId}/attachments/createUploadSession`).post({
        AttachmentItem: { attachmentType: 'file', name: filename, size: totalSize },
      }),
    );

    let offset = 0;
    let chunkIndex = 0;
    while (offset < totalSize) {
      const end = Math.min(offset + UPLOAD_CHUNK_SIZE, totalSize);
      const chunk = data.subarray(offset, end);
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
      // 308 (Resume Incomplete) is the expected response for intermediate chunks;
      // only the final chunk returns 200/201.
      if (!response.ok && response.status !== 308) {
        const text = await response.text();
        throw new Error(`Upload session chunk failed (${response.status}): ${text}`);
      }
      await response.body?.cancel();
      chunkIndex++;
      if (chunkIndex % 20 === 0) {
        this.logger.log({
          msg: 'Chunks uploaded',
          userProfileId,
          draftId,
          filename: createSmeared(filename),
          chunkIndex,
          totalChunks,
          bytesUploaded: end,
          totalBytes: totalSize,
        });
      }
      offset = end;
    }

    this.logger.log({
      msg: 'Chunks uploaded',
      userProfileId,
      draftId,
      filename: createSmeared(filename),
      chunkIndex,
      totalChunks,
      bytesUploaded: offset,
      totalBytes: totalSize,
    });
    return { status: 'success' };
  }
}
