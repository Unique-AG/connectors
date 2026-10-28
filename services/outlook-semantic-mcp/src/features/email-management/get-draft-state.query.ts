import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import * as z from 'zod';
import { encodeGraphItemIdForUrlPath } from '~/msgraph/encode-graph-item-id-for-url-path';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';

const DraftStateResponseSchema = z.object({
  isDraft: z.boolean().optional(),
  subject: z.string().nullable().optional(),
  attachments: z
    .array(
      z.object({
        id: z.string(),
        name: z.string(),
        size: z.number().optional(),
        isInline: z.boolean().optional(),
      }),
    )
    .default([]),
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
  }: {
    userProfileId: string;
    draftId: string;
    idIsImmutable?: boolean;
    mailbox?: string;
  }): Promise<DraftState> {
    const prefix = mailbox ? `/users/${mailbox}` : '/me';
    const client = this.graphClientFactory.createClientForUser(userProfileId);

    try {
      let request = client
        .api(`${prefix}/messages/${encodeGraphItemIdForUrlPath(draftId)}`)
        .select('isDraft,subject')
        .expand('attachments($select=id,name,size,isInline)');
      if (idIsImmutable) {
        request = request.header('Prefer', 'IdType="ImmutableId"');
      }
      const message = DraftStateResponseSchema.parse(await request.get());

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
        attachments: message.attachments.map(({ id, name, isInline }) => ({
          id,
          name,
          isInline: isInline === true,
        })),
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
