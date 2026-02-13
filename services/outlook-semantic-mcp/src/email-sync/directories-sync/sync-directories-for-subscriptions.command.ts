import { Inject, Injectable } from '@nestjs/common';
import { eq, sql } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, directoriesSync, subscriptions } from '~/drizzle';
import { SyncDirectoriesWithDeltaCommand } from './sync-directories-with-delta.command';

@Injectable()
export class SyncDirectoriesForSubscriptionsCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private syncDirectoriesWithDeltaCommand: SyncDirectoriesWithDeltaCommand,
  ) {}

  public async run() {
    const results = await this.db
      .select()
      .from(subscriptions)
      .leftJoin(directoriesSync, eq(subscriptions.userProfileId, directoriesSync.userProfileId))
      .orderBy(sql`${directoriesSync.lastDeltaSyncRunedAt.name} desc nulls first`)
      .limit(10)
      .execute();

    for (const result of results) {
      await this.syncDirectoriesWithDeltaCommand.run(result.subscriptions.subscriptionId);
    }
  }
}
