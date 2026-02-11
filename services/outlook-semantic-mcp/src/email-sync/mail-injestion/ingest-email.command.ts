import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import { DRIZZLE, DrizzleDatabase, userProfiles } from '~/drizzle';
import { UniqueFilesService } from '~/unique/unique-files.service';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage } from './utils/get-metadata-from-message';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';

@Injectable()
export class IngestEmailCommand {
  constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly getMessageDetailsQuery: GetMessageDetailsQuery,
    private readonly uniqueFileService: UniqueFilesService,
  ) {}

  @Span()
  public async run({
    userProfileId,
    messageId,
  }: {
    userProfileId: string;
    messageId: string;
  }): Promise<void> {
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, userProfileId),
    });
    assert.ok(userProfile, `User Profile missing for id: ${userProfileId}`);
    assert.ok(userProfile.email, `User Profile email missing for: ${userProfile.id}`);
    const graphMessage = await this.getMessageDetailsQuery.run({
      userProfileId: userProfile.id,
      messageId,
    });
    const metadata = getMetadataFromMessage(graphMessage);
    const fileKey = getUniqueKeyForMessage(userProfile.email, graphMessage);
    const file = this.uniqueFileService.getFilesByKeys([fileKey]);
    if (isNullish(file)) {
      return;
    }
    // TODO: Injest the file in unique.
  }
}
