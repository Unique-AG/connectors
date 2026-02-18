import { Injectable } from '@nestjs/common';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage } from './utils/get-metadata-from-message';

@Injectable()
export class UpdateMetadataCommand {
  public constructor(private readonly getMessageDetailsQuery: GetMessageDetailsQuery) {}

  public async run({
    userProfileId,
    messageId,
  }: {
    userProfileId: string;
    messageId: string;
    key: string;
  }): Promise<void> {
    const message = await this.getMessageDetailsQuery.run({
      userProfileId,
      messageId,
    });
    const _metadata = getMetadataFromMessage(message);
    // TODO: Update metadata
  }
}
