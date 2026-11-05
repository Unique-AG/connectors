import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { z } from 'zod';
import { BuildWebLinksCommand } from '~/features/graph-utils/build-web-links.command';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { graphMessagePath } from '~/msgraph/graph-message-path';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { toGraphRecipients } from './draft-recipients';
import { GetDraftStateQuery } from './get-draft-state.query';

const UpdateMessageResponseSchema = z.object({
  id: z.string(),
  webLink: z.string().optional(),
});

interface UpdateDraftEmailInput {
  draftId: string;
  idIsImmutable?: boolean;
  mailbox?: string;
  parentFolderId?: string;
  subject?: string;
  content?: string;
  toRecipients?: Array<{ name?: string; email: string }>;
  ccRecipients?: Array<{ name?: string; email: string }>;
}

export type UpdateDraftEmailResult =
  | { success: false; message: string }
  | { success: true; draftId: string; webLink?: string; message: string };

@Injectable()
export class UpdateDraftEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getDraftStateQuery: GetDraftStateQuery,
    private readonly buildWebLinksCommand: BuildWebLinksCommand,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    input: UpdateDraftEmailInput,
  ): Promise<UpdateDraftEmailResult> {
    const userProfileIdString = userProfileId.toString();

    const draftState = await this.getDraftStateQuery.run({
      userProfileId: userProfileIdString,
      draftId: input.draftId,
      idIsImmutable: input.idIsImmutable,
      mailbox: input.mailbox,
      parentFolderId: input.parentFolderId,
      requireCompleteAttachments: false,
    });
    if (draftState.status === 'failed') {
      return { success: false, message: draftState.message };
    }

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const client = this.graphClientFactory.createClientForUser(userProfileIdString);

    // Graph keeps every property that is absent from the PATCH body.
    const patchBody = {
      ...(input.subject !== undefined && { subject: input.subject }),
      ...(input.content !== undefined && {
        body: { contentType: 'HTML', content: input.content },
      }),
      ...(input.toRecipients && { toRecipients: toGraphRecipients(input.toRecipients) }),
      ...(input.ccRecipients && { ccRecipients: toGraphRecipients(input.ccRecipients) }),
    };

    let patchResponse: unknown;
    try {
      let graphRequest = client.api(
        graphMessagePath({
          messageId: input.draftId,
          mailbox: input.mailbox,
          folderId: input.parentFolderId,
        }),
      );
      if (input.idIsImmutable) {
        graphRequest = graphRequest.header('Prefer', 'IdType="ImmutableId"');
      }
      patchResponse = await graphRequest.patch(patchBody);
    } catch (err) {
      this.logger.error({
        userProfileId: userProfileIdString,
        msg: 'Failed to update draft email via Microsoft Graph',
        err,
      });
      return {
        success: false,
        message: 'Failed to update draft email via Microsoft Graph. Nothing was changed.',
      };
    }

    // The draft is updated from here on: what follows only decorates the answer and must not turn
    // it into a failure, or the agent would report an applied edit as lost and retry it.
    const message = UpdateMessageResponseSchema.safeParse(patchResponse);
    const draftId = message.success ? message.data.id : input.draftId;
    const webLink = await this.buildWebLink({
      userProfileId: userProfileIdString,
      userProfileEmail: userProfile.email,
      mailbox: input.mailbox ?? userProfile.email,
      draftId,
      isImmutable: input.idIsImmutable === true,
      graphWebLink: message.success ? message.data.webLink : undefined,
    });

    return {
      success: true,
      draftId,
      ...(webLink && { webLink }),
      message: 'Draft email updated successfully.',
    };
  }

  // See BuildWebLinksCommand for why the Graph webLink cannot be used directly for delegated mailboxes.
  private async buildWebLink({
    userProfileId,
    userProfileEmail,
    mailbox,
    draftId,
    isImmutable,
    graphWebLink,
  }: {
    userProfileId: string;
    userProfileEmail: string;
    mailbox: string;
    draftId: string;
    isImmutable: boolean;
    graphWebLink: string | undefined;
  }): Promise<string | undefined> {
    try {
      const webLinks = await this.buildWebLinksCommand.run({
        userProfileId,
        userProfileEmail,
        ids: [{ id: draftId, isImmutable, mailbox, webLink: graphWebLink ?? '' }],
      });
      return webLinks.get(mailbox, draftId);
    } catch (err) {
      this.logger.warn({
        userProfileId,
        msg: 'Draft email updated, but its web link could not be built',
        err,
      });
      return undefined;
    }
  }
}
