import { Injectable, InternalServerErrorException, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

export interface CreateDraftEmailInput {
  subject: string;
  content: string;
  contentType: 'html' | 'text';
  toRecipients: Array<{ name?: string; email: string }>;
  ccRecipients?: Array<{ name?: string; email: string }>;
  attachments?: Array<{ filename: string; contentBytes: string; contentType: string }>;
}

export type CreateDraftEmailResult =
  | { success: false; message: string }
  | { success: true; draftId: string; message: string };

@Injectable()
export class CreateDraftEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

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

    if (input.attachments && input.attachments.length > 0) {
      body.attachments = input.attachments.map((a) => ({
        '@odata.type': '#microsoft.graph.fileAttachment',
        name: a.filename,
        contentType: a.contentType,
        contentBytes: a.contentBytes,
      }));
    }

    try {
      const client = this.graphClientFactory.createClientForUser(userProfileIdString);
      const message = await client.api('/me/messages').post(body);
      return {
        success: true,
        draftId: message.id,
        message: 'Draft email created successfully.',
      };
    } catch (err) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to create draft email via Microsoft Graph',
        err,
      });
      throw new InternalServerErrorException('Failed to create draft email via Microsoft Graph');
    }
  }
}
