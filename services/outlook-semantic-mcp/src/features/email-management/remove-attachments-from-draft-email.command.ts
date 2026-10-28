import { Injectable, Logger } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { encodeGraphItemIdForUrlPath } from '~/msgraph/encode-graph-item-id-for-url-path';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { DraftAttachment } from './get-draft-state.query';

interface RemoveAttachmentsInput {
  draftId: string;
  idIsImmutable?: boolean;
  mailbox?: string;
  attachments: DraftAttachment[];
}

export interface RemoveAttachmentsResult {
  removed: string[];
  failed: { fileName: string; reason: string }[];
}

@Injectable()
export class RemoveAttachmentsFromDraftEmailCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly graphClientFactory: GraphClientFactory) {}

  @Span()
  public async run(
    userProfileId: UserProfileTypeID,
    { draftId, idIsImmutable, mailbox, attachments }: RemoveAttachmentsInput,
  ): Promise<RemoveAttachmentsResult> {
    const userProfileIdString = userProfileId.toString();
    const client = this.graphClientFactory.createClientForUser(userProfileIdString);
    const prefix = mailbox ? `/users/${mailbox}` : '/me';
    const messagePath = `${prefix}/messages/${encodeGraphItemIdForUrlPath(draftId)}`;

    const result: RemoveAttachmentsResult = { removed: [], failed: [] };
    for (const attachment of attachments) {
      try {
        let request = client.api(
          `${messagePath}/attachments/${encodeGraphItemIdForUrlPath(attachment.id)}`,
        );
        if (idIsImmutable) {
          request = request.header('Prefer', 'IdType="ImmutableId"');
        }
        await request.delete();
        result.removed.push(attachment.name);
      } catch (err) {
        this.logger.warn({
          userProfileId: userProfileIdString,
          draftId,
          msg: 'Failed to remove attachment from draft via Microsoft Graph',
          err,
        });
        result.failed.push({
          fileName: attachment.name,
          reason: err instanceof Error ? err.message : String(err),
        });
      }
    }
    return result;
  }
}
