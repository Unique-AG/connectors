import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish, isNullish } from 'remeda';
import { DRIZZLE, DrizzleDatabase, directories, userProfiles } from '~/drizzle';
import { UniqueFilesService } from '~/unique/unique-files.service';
import { GetMessageDetailsQuery } from './get-message-details.query';
import { getMetadataFromMessage } from './utils/get-metadata-from-message';
import { getUniqueKeyForMessage } from './utils/get-unique-key-for-message';

@Injectable()
export class IngestEmailCommand {
  public constructor(
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

    const _metadata = getMetadataFromMessage(graphMessage);
    const fileKey = getUniqueKeyForMessage(userProfile.email, graphMessage);
    // => Here do full file ingestion.
    const files = await this.uniqueFileService.getFilesByKeys([fileKey]);
    const file = files.at(0);

    const parentDirectory = await this.db.query.directories.findFirst({
      where: eq(directories.providerDirectoryId, graphMessage.parentFolderId),
    });

    // Parent directory should exist because once he connects we run a full directory sync. If it's not there
    // we thrust that the full sync will catch this email. TODO: Check with Michat if we should Throw error.
    if (!parentDirectory?.ignoreForSync) {
      if (isNonNullish(file)) {
        // DELETE FROM UNIQUE
      }
      return;
    }

    if (isNullish(file)) {
      // TODO: Injest the file in unique.
      return;
    }
    // TODO:
    // Compare sentDateTime - sentDateTime
    //    => if not equal reingest + metadata update
    //    => if equal => compare metadata and update
  }
}
