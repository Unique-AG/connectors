import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span } from 'nestjs-otel';
import { z } from 'zod';
import { type UniqueConfigNamespaced } from '~/config';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { type ParsedUri, parseAttachmentUri } from './parse-attachment-uri';
import { uploadChunk } from './upload-chunk';

const UploadSessionSchema = z.object({ uploadUrl: z.string() });

const UPLOAD_CHUNK_SIZE = 13 * 327680; // 4,259,840 bytes — must be a multiple of 320 KiB (327,680) per MS Graph API requirement

export interface AddAttachmentsInput {
  draftId: string;
  attachments: string[];
  chatId?: string;
}

export interface AttachmentFailure {
  uri: string;
  reason: string;
}

export interface AddAttachmentsResult {
  attachmentsFailed: AttachmentFailure[];
}

type AttachmentContent =
  | { data: Buffer; filename: string; size: number }
  | { failure: AttachmentFailure };

type ResolvedUniqueIdentity = { userId: string; companyId: string } | null;

@Injectable()
export class AddAttachmentsToDraftEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    @InjectUniqueApi() private readonly uniqueApiClient: UniqueApiClient,
    private readonly configService: ConfigService<UniqueConfigNamespaced, true>,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: AddAttachmentsInput,
  ): Promise<AddAttachmentsResult> {
    const userProfileIdString = userProfileId.toString();
    const client = this.graphClientFactory.createClientForUser(userProfileIdString);
    const attachmentsFailed: AttachmentFailure[] = [];
    const profile = await this.getUserProfileQuery.run(userProfileId);

    this.logger.log({
      msg: 'Starting attachment upload',
      userProfileId: userProfileIdString,
      draftId: input.draftId,
      attachmentCount: input.attachments.length,
    });

    const uniqueIdentity: { identity: ResolvedUniqueIdentity; wasResolved: boolean } = {
      identity: null,
      wasResolved: false,
    };

    for (const uri of input.attachments) {
      try {
        const parsed = parseAttachmentUri(uri);
        let attachment: AttachmentContent;

        switch (parsed.type) {
          case 'unique':
            if (!uniqueIdentity.wasResolved) {
              uniqueIdentity.identity = await this.resolveUniqueIdentity(profile.email);
              uniqueIdentity.wasResolved = true;
              this.logger.log({
                msg: uniqueIdentity.identity ? 'Unique identity resolved' : 'Unique identity could not be resolved',
                userProfileId: userProfileIdString,
              });
            }
            attachment = await this.resolveUniqueAttachment({
              parsed,
              uri,
              uniqueIdentity: uniqueIdentity.identity,
              fallbackChatId: input.chatId,
            });
            break;
          case 'data':
            attachment = this.resolveDataAttachment(parsed);
            break;
        }

        if ('failure' in attachment) {
          this.logger.warn({
            msg: 'Attachment resolution failed',
            userProfileId: userProfileIdString,
            draftId: input.draftId,
            uri,
            reason: attachment.failure.reason,
          });
          attachmentsFailed.push(attachment.failure);
          continue;
        }

        await this.uploadToGraph(
          client,
          input.draftId,
          attachment.data,
          attachment.filename,
          attachment.size,
          userProfileIdString,
        );

        this.logger.log({
          msg: 'Attachment uploaded successfully',
          userProfileId: userProfileIdString,
          draftId: input.draftId,
          uri,
          filename: attachment.filename,
          sizeBytes: attachment.size,
        });
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        this.logger.warn({
          err,
          userProfileId: userProfileIdString,
          draftId: input.draftId,
          uri,
          msg: 'Attachment failed',
        });
        attachmentsFailed.push({ uri, reason });
      }
    }

    this.logger.log({
      msg: 'Attachment upload run complete',
      userProfileId: userProfileIdString,
      draftId: input.draftId,
      total: input.attachments.length,
      succeeded: input.attachments.length - attachmentsFailed.length,
      failed: attachmentsFailed.length,
    });

    return { attachmentsFailed };
  }

  private async resolveUniqueAttachment({
    parsed,
    uri,
    uniqueIdentity,
    fallbackChatId,
  }: {
    parsed: Extract<ParsedUri, { type: 'unique' }>;
    uri: string;
    uniqueIdentity: ResolvedUniqueIdentity;
    fallbackChatId?: string;
  }): Promise<AttachmentContent> {
    const chatId = parsed.chatId || fallbackChatId;
    if (!chatId) {
      return { failure: { uri, reason: 'Missing chatId for unique:// attachment' } };
    }

    const uniqueConfig = this.configService.get('unique', { infer: true });
    if (uniqueConfig.serviceAuthMode !== 'cluster_local') {
      return { failure: { uri, reason: 'App is not running in cluster local' } };
    }
    if (!uniqueIdentity) {
      return { failure: { uri, reason: 'Could not resolve unique identity' } };
    }

    // We impersonate the Unique user so the content API authorizes
    // the download as if the user themselves initiated it.
    const contentUrl = `${uniqueConfig.ingestionServiceBaseUrl}/v1/content/${encodeURIComponent(parsed.contentId)}/file`;

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
        failure: { uri, reason: `Unique content download failed (${response.status}): ${text}` },
      };
    }

    const contentDisposition = response.headers.get('content-disposition');
    const filenameMatch = contentDisposition?.match(/filename="?([^";]+)"?/);
    const filename = filenameMatch?.[1] ?? parsed.contentId;

    const data = Buffer.from(await response.arrayBuffer());
    return { data, filename, size: data.length };
  }

  private resolveDataAttachment(parsed: Extract<ParsedUri, { type: 'data' }>): AttachmentContent {
    return { data: parsed.data, filename: parsed.filename, size: parsed.data.length };
  }

  private async resolveUniqueIdentity(email: string): Promise<ResolvedUniqueIdentity> {
    const uniqueConfig = this.configService.get('unique', { infer: true });
    if (uniqueConfig.serviceAuthMode !== 'cluster_local') {
      return null;
    }
    try {
      const uniqueUser = await this.uniqueApiClient.users.findByEmail(email);
      if (uniqueUser) {
        return { userId: uniqueUser.id, companyId: uniqueUser.companyId };
      }
    } catch (err) {
      this.logger.error({ msg: 'Failed to resolve unique user identity', err });
    }
    return null;
  }

  private async uploadToGraph(
    client: ReturnType<GraphClientFactory['createClientForUser']>,
    draftId: string,
    data: Buffer,
    filename: string,
    totalSize: number,
    userProfileId: string,
  ): Promise<void> {
    if (totalSize <= 3 * 1024 * 1024) {
      this.logger.log({
        msg: 'Uploading attachment via simple POST',
        userProfileId,
        draftId,
        filename,
        sizeBytes: totalSize,
      });
      await client.api(`/me/messages/${draftId}/attachments`).post({
        '@odata.type': '#microsoft.graph.fileAttachment',
        name: filename,
        contentBytes: data.toString('base64'),
      });
      return;
    }

    const totalChunks = Math.ceil(totalSize / UPLOAD_CHUNK_SIZE);
    this.logger.log({
      msg: 'Uploading attachment via upload session',
      userProfileId,
      draftId,
      filename,
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
      await uploadChunk(uploadUrl, chunk, offset, totalSize);
      chunkIndex++;
      this.logger.log({
        msg: 'Chunk uploaded',
        userProfileId,
        draftId,
        filename,
        chunkIndex,
        totalChunks,
        bytesUploaded: end,
        totalBytes: totalSize,
      });
      offset = end;
    }
  }
}
