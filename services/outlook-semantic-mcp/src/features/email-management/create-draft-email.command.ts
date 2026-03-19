import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { z } from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import {
  AddAttachmentsToDraftEmailCommand,
  type AttachmentFailure,
} from './add-attachments-to-draft-email.command';

const CreateMessageResponseSchema = z.object({ id: z.string(), webLink: z.string().optional() });

export interface CreateDraftEmailInput {
  subject: string;
  content: string;
  contentType: 'html' | 'text';
  toRecipients: Array<{ name?: string; email: string }>;
  ccRecipients?: Array<{ name?: string; email: string }>;
  attachments?: {
    fileName: string;
    data: string;
  }[];
  chatId?: string;
}

export type CreateDraftEmailResult =
  | { success: false; message: string }
  | {
      success: true;
      draftId: string;
      webLink?: string;
      message: string;
      attachmentsFailed?: AttachmentFailure[];
    };

@Injectable()
export class CreateDraftEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly addAttachmentsToDraftEmailCommand: AddAttachmentsToDraftEmailCommand,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: CreateDraftEmailInput,
  ): Promise<CreateDraftEmailResult> {
    const createDraftResult = await this.createDraft(userProfileId, input);
    if (!createDraftResult.success) {
      return createDraftResult;
    }

    const attachments = input.attachments;

    if (!attachments || !attachments.length) {
      return createDraftResult;
    }

    const attachmentResult = await this.addAttachmentsToDraftEmailCommand.run(userProfileId, {
      draftId: createDraftResult.draftId,
      attachments,
      chatId: input.chatId,
    });

    if (!attachmentResult.attachmentsFailed.length) {
      return createDraftResult;
    }

    return {
      ...createDraftResult,
      attachmentsFailed: attachmentResult.attachmentsFailed,
    };
  }

  @Span()
  public async createDraft(
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

    try {
      const message = CreateMessageResponseSchema.parse(
        await client.api('/me/messages').post(body),
      );

      return {
        success: true,
        draftId: message.id,
        ...(message.webLink && { webLink: message.webLink }),
        message: 'Draft email created successfully.',
      };
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
  }
}
