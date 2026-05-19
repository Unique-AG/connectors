import { Inject, Injectable } from '@nestjs/common';
import { eq, gt, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, directoriesSync, subscriptions, userProfiles } from '~/db';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { SyncDirectoriesCommand } from './sync-directories.command';
import { unique } from 'remeda';

@Injectable()
export class SyncDirectoriesForSubscriptionsCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private syncDirectoriesCommand: SyncDirectoriesCommand,
  ) {}

  @Span()
  public async run() {
    const sharedMailboxes = await this.db
      .select({ id: userProfiles.id })
      .from(userProfiles)
      .where(eq(userProfiles.source, 'shared-mailbox'));

    const usersWithActiveSubscriptions = await this.db
      .select()
      .from(subscriptions)
      .leftJoin(directoriesSync, eq(subscriptions.userProfileId, directoriesSync.userProfileId))
      .where(gt(subscriptions.expiresAt, sql`now()`))
      .orderBy(sql`${directoriesSync.lastDeltaSyncRanAt.name} desc nulls first`)
      .limit(10)
      .execute();

    const ids = unique([
      ...sharedMailboxes.map((item) => item.id),
      ...usersWithActiveSubscriptions.map((item) => item.subscriptions.userProfileId),
    ]);

    for (const id of ids) {
      await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(id));
    }
  }
}
