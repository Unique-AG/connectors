import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { graphMessagePath } from '~/msgraph/graph-message-path';

const DraftStateResponseSchema = z.object({
  isDraft: z.boolean().optional(),
  subject: z.string().nullable().optional(),
  attachments: z
    .array(
      z.object({
        id: z.string(),
        name: z.string().nullish(),
        isInline: z.boolean().nullish(),
      }),
    )
    // Graph sends null, not [], for a message expanded with no attachments.
    .nullish()
    .transform((attachments) => attachments ?? []),
  'attachments@odata.nextLink': z.string().optional(),
});

export interface DraftAttachment {
  id: string;
  name: string;
  isInline: boolean;
}

export type DraftState =
  | { status: 'draft'; subject: string | null; attachments: DraftAttachment[] }
  | { status: 'failed'; message: string };

@Injectable()
export class GetDraftStateQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run({
    userProfileId,
    draftId,
    idIsImmutable,
    mailbox,
    parentFolderId,
  }: {
    userProfileId: string;
    draftId: string;
    idIsImmutable?: boolean;
    mailbox?: string;
    parentFolderId?: string;
  }): Promise<DraftState> {
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    try {
      let request = client
        .api(graphMessagePath({ messageId: draftId, mailbox, folderId: parentFolderId }))
        .select('isDraft,subject')
        .expand('attachments($select=id,name,isInline)');
      if (idIsImmutable) {
        request = request.header('Prefer', 'IdType="ImmutableId"');
      }
      const message = DraftStateResponseSchema.parse(await request.get());

      if (message['attachments@odata.nextLink'] !== undefined) {
        // The edit tools remove attachments by name, so a list cut short would hide the one to remove.
        return {
          status: 'failed',
          message:
            'The draft has more attachments than Microsoft Graph returned in one answer, so its attachment list is incomplete. Nothing was changed.',
        };
      }
      if (message.isDraft !== true) {
        return {
          status: 'failed',
          message:
            'This message is no longer a draft — it was probably already sent — so it cannot be edited. Nothing was changed. Create a new draft with `draft_email` if the user wants another message.',
        };
      }
      return {
        status: 'draft',
        subject: message.subject ?? null,
        attachments: message.attachments.flatMap(({ id, name, isInline }) =>
          name ? [{ id, name, isInline: isInline === true }] : [],
        ),
      };
    } catch (err) {
      this.logger.error({
        userProfileId,
        draftId,
        msg: 'Failed to read draft email via Microsoft Graph',
        err,
      });
      return {
        status: 'failed',
        message:
          'Could not read the draft from Microsoft Graph. It may have been deleted or moved, or the id may be wrong. Nothing was changed. Search again with `search_emails` in the Drafts folder.',
      };
    }
  }
}
