import { UniqueApiClient } from '@unique-ag/unique-api';
import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import { z } from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { uploadChunk } from './upload-chunk';

const CreateMessageResponseSchema = z.object({ id: z.string(), webLink: z.string().optional() });
const UploadSessionSchema = z.object({ uploadUrl: z.string() });

export interface CreateDraftEmailInput {
  subject: string;
  content: string;
  contentType: 'html' | 'text';
  toRecipients: Array<{ name?: string; email: string }>;
  ccRecipients?: Array<{ name?: string; email: string }>;
  attachmentIds?: string[];
}

export type CreateDraftEmailResult =
  | { success: false; message: string }
  | {
      success: true;
      draftId: string;
      webLink?: string;
      message: string;
      attachmentsFailed?: Array<{ contentId: string; reason: string }>;
    };

@Injectable()
export class CreateDraftEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    @InjectUniqueApi() private readonly uniqueApiClient: UniqueApiClient,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: CreateDraftEmailInput,
  ): Promise<CreateDraftEmailResult> {
    const userProfileIdString = userProfileId.toString();

    const body: Record<string, unknown> = {
      subject: input.subject,
      body: {
        contentType: input.contentType === 'html' ? 'HTML' : 'Text',
        content: input.content,
      },
      toRecipients: input.toRecipients.map((r) => ({
        emailAddress: { name: r.name, address: r.email },
      })),
    };

    if (input.ccRecipients && input.ccRecipients.length > 0) {
      body.ccRecipients = input.ccRecipients.map((r) => ({
        emailAddress: { name: r.name, address: r.email },
      }));
    }

    const client = this.graphClientFactory.createClientForUser(userProfileIdString);

    let draftId: string;
    let webLink: string | undefined;
    try {
      const message = CreateMessageResponseSchema.parse(
        await client.api('/me/messages').post(body),
      );
      draftId = message.id;
      webLink = message.webLink;
    } catch (err) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to create draft email via Microsoft Graph',
        err,
      });
      return {
        success: false,
        message: 'Failed to create draft email via Microsoft Graph',
      };
    }

    const attachmentsFailed: Array<{ contentId: string; reason: string }> = [];

    for (const contentId of input.attachmentIds ?? []) {
      try {
        const streamed = await this.uniqueApiClient.content.streamContentById(contentId);

        // MS Graph upload sessions require the total file size upfront.
        // If Content-Length was absent, buffer the stream first to determine it.
        let totalSize: number;
        let source: AsyncIterable<unknown>;

        if (!isNullish(streamed.size)) {
          totalSize = streamed.size;
          source = streamed.stream;
        } else {
          // If we do not know the file size it's the worst case cause createUploadSession
          // expects a size up front.
          const parts: Buffer[] = [];
          for await (const chunk of streamed.stream) {
            parts.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
          }
          const buf = Buffer.concat(parts);
          totalSize = buf.length;
          source = (async function* () {
            yield buf;
          })();
        }

        const { uploadUrl } = UploadSessionSchema.parse(
          await client.api(`/me/messages/${draftId}/attachments/createUploadSession`).post({
            AttachmentItem: { attachmentType: 'file', name: streamed.filename, size: totalSize },
          }),
        );

        let offset = 0;
        let pending = Buffer.alloc(0);
        // 5 MiB per chunk — satisfies MS Graph's requirement of multiples of 320 KiB (5 MiB = 16 × 320 KiB)
        const UPLOAD_CHUNK_SIZE = 5 * 1024 * 1024;

        for await (const raw of source) {
          pending = Buffer.concat([
            pending,
            Buffer.isBuffer(raw) ? raw : Buffer.from(raw as ArrayLike<number>),
          ]);
          while (pending.length >= UPLOAD_CHUNK_SIZE) {
            await uploadChunk(uploadUrl, pending.subarray(0, UPLOAD_CHUNK_SIZE), offset, totalSize);
            offset += UPLOAD_CHUNK_SIZE;
            pending = pending.subarray(UPLOAD_CHUNK_SIZE);
          }
        }

        if (pending.length > 0) {
          await uploadChunk(uploadUrl, pending, offset, totalSize);
        }
      } catch (err) {
        const reason = err instanceof Error ? err.message : String(err);
        this.logger.warn({
          err,
          userProfileId: userProfileIdString,
          msg: 'Failed to attach content to draft',
          contentId,
          reason,
        });
        attachmentsFailed.push({ contentId, reason });
      }
    }

    return {
      success: true,
      draftId,
      ...(webLink && { webLink }),
      message: 'Draft email created successfully.',
      ...(attachmentsFailed.length > 0 && { attachmentsFailed }),
    };
  }
}
