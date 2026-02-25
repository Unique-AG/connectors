import { Inject, Injectable } from '@nestjs/common';
import { eq, gt, sql } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, directoriesSync, subscriptions } from '~/db';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SyncDirectoriesCommand } from './sync-directories.command';

@Injectable()
export class SyncDirectoriesForSubscriptionsCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private syncDirectoriesCommand: SyncDirectoriesCommand,
  ) {}

  public async run() {
    const results = await this.db
      .select()
      .from(subscriptions)
      .leftJoin(directoriesSync, eq(subscriptions.userProfileId, directoriesSync.userProfileId))
      .where(gt(subscriptions.expiresAt, sql`now()`))
      .orderBy(sql`${directoriesSync.lastDeltaSyncRanAt.name} desc nulls first`)
      .limit(10)
      .execute();

    for (const result of results) {
      await this.syncDirectoriesCommand.run(
        convertUserProfileIdToTypeId(result.subscriptions.userProfileId),
      );
    }
  }
}
