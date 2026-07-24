import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq, isNotNull, or, sql } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, DrizzleDatabase, directoriesSync, userProfiles } from '~/db';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { getRetryAfterMs } from '~/utils/get-retry-after-ms';
import { isRateLimitError } from '~/utils/is-rate-limit-error';
import { makeRetryResponse, withRetryAttempts } from '~/utils/with-retry-attempts';
import { SyncDirectoriesCommand } from './sync-directories.command';

@Injectable()
export class SyncDirectoriesForAllUserProfilesCommand {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private syncDirectoriesCommand: SyncDirectoriesCommand,
  ) {}

  @Span()
  public async run() {
    const results = await this.db
      .select({ id: sql<string>`${userProfiles.id}` })
      .from(userProfiles)
      .leftJoin(directoriesSync, eq(directoriesSync.userProfileId, userProfiles.id))
      .where(
        or(
          eq(userProfiles.source, 'shared-mailbox'),
          and(eq(userProfiles.source, 'oauth'), isNotNull(userProfiles.accessToken)),
        ),
      )
      .orderBy(sql`${directoriesSync.lastDeltaSyncRanAt} asc nulls first`)
      .limit(10);

    type SuccessOrFailureResult = 'success' | 'failed';

    for (const { id } of results) {
      await withRetryAttempts<SuccessOrFailureResult>({
        fn: async (): Promise<SuccessOrFailureResult> => {
          await this.syncDirectoriesCommand.run(convertUserProfileIdToTypeId(id));
          return 'success';
        },
        onError: ({ error, wasLastAttempt }) => {
          if (isRateLimitError(error)) {
            if (wasLastAttempt) {
              throw error;
            }
            return makeRetryResponse(getRetryAfterMs(error));
          }

          this.logger.warn({ error, msg: `User skipped for directories sync`, userProfileId: id });
          return 'failed';
        },
      });
    }
  }
}
