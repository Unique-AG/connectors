import { Inject, Injectable } from '@nestjs/common';
import { eq, gt, or, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, directoriesSync, subscriptions, userProfiles } from '~/db';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { rethrowRateLimitError, withRetryAttempts } from '~/utils/with-retry-attempts';
import { SyncDirectoriesCommand } from './sync-directories.command';

@Injectable()
export class SyncDirectoriesForAllUserProfilesCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private syncDirectoriesCommand: SyncDirectoriesCommand,
  ) {}

  @Span()
  public async run() {
    const results = await this.db
      .selectDistinct({ id: sql<string>`${userProfiles.id}` })
      .from(userProfiles)
      .leftJoin(subscriptions, eq(subscriptions.userProfileId, userProfiles.id))
      .leftJoin(directoriesSync, eq(directoriesSync.userProfileId, userProfiles.id))
      .where(or(eq(userProfiles.source, 'shared-mailbox'), gt(subscriptions.expiresAt, sql`now()`)))
      .orderBy(sql`${directoriesSync.lastDeltaSyncRanAt.name} asc nulls first`)
      .limit(10);

    type SuccessOrFailureResult = 'success' | 'failed';

    for (const { id } of results) {
      await withRetryAttempts<SuccessOrFailureResult>({
        fn: async (): Promise<SuccessOrFailureResult> => {
          await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(id));
          return 'success';
        },
        onError: rethrowRateLimitError,
      });
    }
  }
}
