import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { UniqueApiClient } from '@unique-ag/unique-api';
import { Span } from 'nestjs-otel';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

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
    try {
      const message = await client.api('/me/messages').post(body) as { id: string };
      draftId = message.id;
    } catch (err) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to create draft email via Microsoft Graph',
        err,
      });
      throw new InternalServerErrorException('Failed to create draft email via Microsoft Graph');
    }

    const attachmentsFailed: Array<{ contentId: string; reason: string }> = [];

    if (input.attachmentIds && input.attachmentIds.length > 0) {
      for (const contentId of input.attachmentIds) {
        try {
          const downloaded = await this.uniqueApiClient.content.downloadContentById(contentId);
          await client.api(`/me/messages/${draftId}/attachments`).post({
            '@odata.type': '#microsoft.graph.fileAttachment',
            name: downloaded.filename,
            contentType: downloaded.mimeType,
            contentBytes: downloaded.data.toString('base64'),
          });
        } catch (err) {
          const reason = err instanceof Error ? err.message : String(err);
          attachmentsFailed.push({ contentId, reason });
        }
      }
    }

    return {
      success: true,
      draftId,
      message: 'Draft email created successfully.',
      ...(attachmentsFailed.length > 0 && { attachmentsFailed }),
    };
  }
}
