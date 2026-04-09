import { Inject, Injectable } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';

type InboxConfig = typeof inboxConfigurations.$inferSelect;

type FullSyncFields = Pick<
  InboxConfig,
  | 'fullSyncNextLink'
  | 'fullSyncBatchIndex'
  | 'fullSyncExpectedTotal'
  | 'fullSyncSkipped'
  | 'fullSyncScheduledForIngestion'
  | 'fullSyncFailedToUploadForIngestion'
  | 'filters'
  | 'oldestReceivedEmailDateTime'
  | 'newestReceivedEmailDateTime'
>;

@Injectable()
export class FindInboxConfigByVersionQuery {
  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(userProfileId: string, version: string): Promise<FullSyncFields | null> {
    const row = await this.db
      .select({
        fullSyncNextLink: inboxConfigurations.fullSyncNextLink,
        fullSyncBatchIndex: inboxConfigurations.fullSyncBatchIndex,
        fullSyncExpectedTotal: inboxConfigurations.fullSyncExpectedTotal,
        fullSyncSkipped: inboxConfigurations.fullSyncSkipped,
        fullSyncScheduledForIngestion: inboxConfigurations.fullSyncScheduledForIngestion,
        fullSyncFailedToUploadForIngestion: inboxConfigurations.fullSyncFailedToUploadForIngestion,
        filters: inboxConfigurations.filters,
        oldestReceivedEmailDateTime: inboxConfigurations.oldestReceivedEmailDateTime,
        newestReceivedEmailDateTime: inboxConfigurations.newestReceivedEmailDateTime,
      })
      .from(inboxConfigurations)
      .where(
        and(
          eq(inboxConfigurations.userProfileId, userProfileId),
          eq(inboxConfigurations.fullSyncVersion, version),
        ),
      )
      .then((rows) => rows[0] ?? null);

    return row;
  }
}
