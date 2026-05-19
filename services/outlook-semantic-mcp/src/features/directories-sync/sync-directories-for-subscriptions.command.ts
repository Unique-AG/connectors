import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq, gt, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { unique } from 'remeda';
import { DRIZZLE, DrizzleDatabase, directoriesSync, subscriptions, userProfiles } from '~/db';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { withRetryAttempts } from '~/utils/with-retry-attempts';
import { SyncDirectoriesCommand } from './sync-directories.command';

@Injectable()
export class SyncDirectoriesForSubscriptionsCommand {
  private logger = new Logger(this.constructor.name);

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
    type SuccessOrFailureResult = 'success' | 'failed';

    for (const id of ids) {
      await withRetryAttempts<SuccessOrFailureResult>({
        fn: async (): Promise<SuccessOrFailureResult> => {
          await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(id));
          return 'success';
        },
        onError: (wasLastAttempt, err) => {
          if (!wasLastAttempt) {
            return;
          }
          this.logger.error({ msg: `Sync directories failed for user: ${id}`, err });
        },
        getResultFailure: () => {
          return 'failed';
        },
      });
    }
  }
}
