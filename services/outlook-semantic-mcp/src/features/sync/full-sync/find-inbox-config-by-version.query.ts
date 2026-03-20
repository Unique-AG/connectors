import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';

type InboxConfig = typeof inboxConfiguration.$inferSelect;

type FullSyncFields = Pick<
  InboxConfig,
  | 'fullSyncNextLink'
  | 'fullSyncBatchIndex'
  | 'fullSyncExpectedTotal'
  | 'fullSyncSkipped'
  | 'fullSyncScheduledForIngestion'
  | 'fullSyncFailedToUploadForIngestion'
  | 'filters'
  | 'oldestCreatedDateTime'
  | 'newestCreatedDateTime'
>;

@Injectable()
export class FindInboxConfigByVersionQuery {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(userProfileId: string, version: string): Promise<FullSyncFields | null> {
    const row = await this.db
      .select({
        fullSyncNextLink: inboxConfiguration.fullSyncNextLink,
        fullSyncBatchIndex: inboxConfiguration.fullSyncBatchIndex,
        fullSyncExpectedTotal: inboxConfiguration.fullSyncExpectedTotal,
        fullSyncSkipped: inboxConfiguration.fullSyncSkipped,
        fullSyncScheduledForIngestion: inboxConfiguration.fullSyncScheduledForIngestion,
        fullSyncFailedToUploadForIngestion: inboxConfiguration.fullSyncFailedToUploadForIngestion,
        filters: inboxConfiguration.filters,
        oldestCreatedDateTime: inboxConfiguration.oldestCreatedDateTime,
        newestCreatedDateTime: inboxConfiguration.newestCreatedDateTime,
      })
      .from(inboxConfiguration)
      .where(
        and(
          eq(inboxConfiguration.userProfileId, userProfileId),
          eq(inboxConfiguration.fullSyncVersion, version),
        ),
      )
      .then((rows) => rows[0] ?? null);

    return row;
  }
}
