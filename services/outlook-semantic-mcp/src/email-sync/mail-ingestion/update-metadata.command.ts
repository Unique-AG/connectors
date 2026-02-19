import { Injectable } from '@nestjs/common';
import { Span } from 'nestjs-otel';
import { traceAttrs } from '~/email-sync/tracing.utils';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage } from './utils/get-metadata-from-message';

@Injectable()
export class UpdateMetadataCommand {
  public constructor(private readonly getMessageDetailsQuery: GetMessageDetailsQuery) {}

  @Span()
  public async run({
    userProfileId,
    messageId,
  }: {
    userProfileId: string;
    messageId: string;
    key: string;
  }): Promise<void> {
    traceAttrs({ user_profile_id: userProfileId, message_id: messageId });
    const message = await this.getMessageDetailsQuery.run({
      userProfileId,
      messageId,
    });
    const _metadata = getMetadataFromMessage(message);
    // TODO: Update metadata
  }
}
