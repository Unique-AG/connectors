import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { z } from 'zod';
import {
  BuildWebLinksCommand,
  webLinkMapKey,
} from '~/features/graph-utils/build-web-links.command';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { encodeGraphItemIdForUrlPath } from '~/msgraph/encode-graph-item-id-for-url-path';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { AddAttachmentsToDraftEmailCommand } from './add-attachments-to-draft-email.command';
import { AttachmentFailure } from './email-attachments/utils';
import { markdownToHtml } from './markdown-to-html';

const CreateMessageResponseSchema = z.object({
  id: z.string(),
  webLink: z.string().optional(),
});

interface CreateDraftEmailInput {
  content: string;
  attachments?: { fileName: string; data: string }[];
  chatId: string | null | undefined;
  mailbox?: string;
  recipientsData:
    | {
        type: 'draft';
        subject: string;
        toRecipients: Array<{ name?: string; email: string }>;
        ccRecipients?: Array<{ name?: string; email: string }>;
      }
    | {
        type: 'reply';
        inReplyToMessageId: string;
        idIsImmutable?: boolean;
      };
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
    private readonly buildWebLinksCommand: BuildWebLinksCommand,
    private readonly getUserProfileQuery: GetUserProfileQuery,
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
      mailbox: input.mailbox,
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
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const recipientsData = input.recipientsData;
    const prefix = input.mailbox ? `/users/${input.mailbox}` : '/me';

    const htmlContent = markdownToHtml(input.content);

    const client = this.graphClientFactory.createClientForUser(userProfileIdString);

    const apiParams =
      recipientsData.type === 'reply'
        ? {
            apiPath: `${prefix}/messages/${encodeGraphItemIdForUrlPath(recipientsData.inReplyToMessageId)}/createReplyAll`,
            body: { comment: htmlContent },
            successMessage: 'Reply-all draft created successfully.',
            idIsImmutable: recipientsData.idIsImmutable === true,
          }
        : {
            apiPath: `${prefix}/messages`,
            body: {
              body: {
                contentType: 'HTML',
                content: htmlContent,
              },
              subject: recipientsData.subject,
              toRecipients: recipientsData.toRecipients.map((item) => ({
                emailAddress: {
                  address: item.email,
                  ...(item.name && { name: item.name }),
                },
              })),
              ccRecipients:
                recipientsData.ccRecipients?.map((item) => ({
                  emailAddress: {
                    address: item.email,
                    ...(item.name && { name: item.name }),
                  },
                })) ?? [],
            },
            successMessage: 'Draft email created successfully.',
            idIsImmutable: false,
          };

    try {
      let graphRequest = client.api(apiParams.apiPath);
      if (apiParams.idIsImmutable) {
        graphRequest = graphRequest.header('Prefer', 'IdType="ImmutableId"');
      }

      const message = CreateMessageResponseSchema.parse(await graphRequest.post(apiParams.body));

      const webLink = await this.buildWebLink({
        userProfileId: userProfileIdString,
        userProfileEmail: userProfile.email,
        messageId: message.id,
        graphWebLink: message.webLink,
        idIsImmutable: apiParams.idIsImmutable,
        mailbox: input.mailbox,
      });

      return {
        success: true,
        draftId: message.id,
        ...(webLink && { webLink }),
        message: apiParams.successMessage,
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

  // See BuildWebLinksCommand for a full explanation of why we cannot use the Graph webLink
  // directly for delegated mailboxes (cloud.microsoft format, broken OWA ItemID).
  private async buildWebLink({
    userProfileId,
    userProfileEmail,
    messageId,
    graphWebLink,
    idIsImmutable,
    mailbox,
  }: {
    userProfileId: string;
    userProfileEmail: string;
    messageId: string;
    graphWebLink: string | undefined;
    idIsImmutable: boolean;
    mailbox: string | null | undefined;
  }): Promise<string | undefined> {
    const messageMailbox = mailbox ?? userProfileEmail;
    const webLinksMap = await this.buildWebLinksCommand.run({
      userProfileId,
      userProfileEmail,
      ids: [
        {
          id: messageId,
          isImmutable: idIsImmutable,
          mailbox: messageMailbox,
          webLink: graphWebLink ?? '',
        },
      ],
    });
    return webLinksMap.get(webLinkMapKey(messageMailbox, messageId));
  }
}
