import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { z } from 'zod';
import { BuildWebLinksCommand } from '~/features/graph-utils/build-web-links.command';
import { GetUserProfileQuery } from '~/features/user-utils/get-user-profile.query';
import { encodeGraphItemIdForUrlPath } from '~/msgraph/encode-graph-item-id-for-url-path';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
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
    });
    if (draftState.status === 'failed') {
      return { success: false, message: draftState.message };
    }

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const prefix = input.mailbox ? `/users/${input.mailbox}` : '/me';
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

    try {
      let graphRequest = client.api(
        `${prefix}/messages/${encodeGraphItemIdForUrlPath(input.draftId)}`,
      );
      if (input.idIsImmutable) {
        graphRequest = graphRequest.header('Prefer', 'IdType="ImmutableId"');
      }
      const message = UpdateMessageResponseSchema.parse(await graphRequest.patch(patchBody));

      // See BuildWebLinksCommand for why the Graph webLink cannot be used directly for delegated mailboxes.
      const messageMailbox = input.mailbox ?? userProfile.email;
      const webLinks = await this.buildWebLinksCommand.run({
        userProfileId: userProfileIdString,
        userProfileEmail: userProfile.email,
        ids: [
          {
            id: message.id,
            isImmutable: input.idIsImmutable === true,
            mailbox: messageMailbox,
            webLink: message.webLink ?? '',
          },
        ],
      });
      const webLink = webLinks.get(messageMailbox, message.id);

      return {
        success: true,
        draftId: message.id,
        ...(webLink && { webLink }),
        message: 'Draft email updated successfully.',
      };
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
  }
}
