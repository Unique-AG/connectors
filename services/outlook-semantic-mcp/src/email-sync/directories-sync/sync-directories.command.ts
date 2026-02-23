import assert from 'node:assert';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Attributes } from '@opentelemetry/api';
import { and, eq, inArray } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNonNullish, isNullish } from 'remeda';
import { DirectoriesSync, directories, directoriesSync } from '~/db';
import { DRIZZLE, DrizzleDatabase } from '~/db/drizzle.module';
import { traceAttrs, traceEvent } from '~/email-sync/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';
import { graphOutlookDirectoriesDeltaResponse } from './microsoft-graph.dtos';
import { SyncDirectoriesForUserProfileCommand } from './sync-directories-for-user-profile.command';

@Injectable()
export class SyncDirectoriesCommand {
  private readonly logger = new Logger(SyncDirectoriesCommand.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly syncDirectoriesForUserProfileCommand: SyncDirectoriesForUserProfileCommand,
  ) {}

  @Span()
  public async run(userProfileTypeId: UserProfileTypeID): Promise<void> {
    traceAttrs({ user_profile_type_id: userProfileTypeId.toString() });
    this.logger.log({
      userProfileTypeId: userProfileTypeId.toString(),
      msg: `Starting directories sync`,
    });

    const userProfile = await this.getUserProfileQuery.run(userProfileTypeId);
    traceAttrs({ user_profile_id: userProfile.id });
    this.logger.log({
      userProfileTypeId: userProfileTypeId.toString(),
      userProfileId: userProfile.id,
      msg: `Resolved user profile`,
    });

    // We have an internal mechanism which can force a sync even if delta query returns nothing.
    // This internal mechanism is used to avoid triggering a full sync because we could not identify
    // the parent directory of an email which lands in our webhook. The logic there happens
    // in the following way.
    // 1. Email lands in our webhook
    // 2. We check if we have the parent directory
    // 2.1 => If we don't have the parent directory we insert a new special directory with a special type and sync the email
    // 2.2 => If we have the directory the sync happens normally.
    // Once the logic above is triggere on the next scheduled delta sync we look if we have any special directory inserted
    // if we find one we force a directory sync to ensure we sync only the necesary folders. Normaly delta query should
    // detect the new directory but as a failback we run the sync anyway using this logic.
    const shouldForceDirectoriesSync = await this.shouldForceDirectoriesSyncForUser(userProfile.id);
    traceAttrs({ should_force_directories_sync: shouldForceDirectoriesSync });
    this.logger.log({
      userProfileId: userProfile.id,
      shouldForceDirectoriesSync,
      msg: `Checked force sync condition`,
    });

    const { shouldSyncDirectories, deltaLink, syncStatsId } = await this.runDeltaQuery(
      userProfile.id,
    );
    traceEvent('delta sync completed', {
      should_sync_directories: shouldSyncDirectories,
      delta_link_present: isNonNullish(deltaLink),
    });
    const logContext: Attributes = {
      userProfileTypeId: userProfileTypeId.toString(),
      userProfileId: userProfile.id,
      shouldSyncDirectories,
      shouldForceDirectoriesSync,
      syncStatsId,
    };
    traceAttrs({ ...logContext, delta_link_present: isNonNullish(deltaLink) });
    if (shouldSyncDirectories || shouldForceDirectoriesSync) {
      traceEvent(`Run directories sync`);
      this.logger.log({ ...logContext, msg: `Run directories sync` });
      await this.syncDirectoriesForUserProfileCommand.run(userProfileTypeId);
      traceEvent('directories sync completed');
      this.logger.log({ ...logContext, msg: `Directories sync completed` });
    } else {
      traceEvent(`Skip directories sync`);
      this.logger.log({ ...logContext, msg: `Skip directories sync` });
    }
    // We do not check the delta link because microsoft returns the same delta link as the current one.
    await this.db
      .update(directoriesSync)
      .set({
        deltaLink,
        lastDeltaSyncRanAt: new Date(),
      })
      .where(eq(directoriesSync.id, syncStatsId))
      .execute();
    this.logger.log({
      ...logContext,
      deltaLinkPresent: isNonNullish(deltaLink),
      msg: `Updated delta sync stats`,
    });
  }

  private async runDeltaQuery(userProfileId: string): Promise<{
    shouldSyncDirectories: boolean;
    deltaLink: string | null;
    syncStatsId: string;
  }> {
    const syncStats = await this.findOrCreateStats(userProfileId);
    const isInitialSync = !syncStats.deltaLink;
    traceAttrs({ delta_query_is_initial_sync: isInitialSync, sync_stats_id: syncStats.id });
    this.logger.log({
      userProfileId,
      syncStatsId: syncStats.id,
      isInitialSync,
      msg: `Running delta query`,
    });

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    let directoriesDeltaResult = await client
      .api(syncStats.deltaLink || `/me/mailFolders/delta`)
      .get();

    let directroriesResponse = graphOutlookDirectoriesDeltaResponse.parse(directoriesDeltaResult);
    let shouldSyncDirectories = false;
    let pageCount = 1;

    if (directroriesResponse.value.length > 0) {
      shouldSyncDirectories = true;
      traceEvent('delta changes detected', {
        page: pageCount,
        change_count: directroriesResponse.value.length,
      });
      this.logger.log({
        userProfileId,
        syncStatsId: syncStats.id,
        changeCount: directroriesResponse.value.length,
        msg: `Delta changes detected`,
      });
      await this.db
        .update(directoriesSync)
        .set({ lastDeltaChangeDetectedAt: new Date() })
        .where(eq(directoriesSync.id, syncStats.id))
        .execute();
    }

    while (directroriesResponse['@odata.nextLink']) {
      pageCount++;
      const previousNextLink = directroriesResponse['@odata.nextLink'];
      directoriesDeltaResult = await client.api(directroriesResponse['@odata.nextLink']).get();
      directroriesResponse = graphOutlookDirectoriesDeltaResponse.parse(directoriesDeltaResult);
      traceEvent('delta query page fetched', {
        page: pageCount,
        change_count: directroriesResponse.value.length,
      });

      if (directroriesResponse['@odata.nextLink']) {
        // We advance the query but we stop advancing on the last response because we want to run the sync and put the
        // final delta with no results once that happens.
        await this.db
          .update(directoriesSync)
          .set({
            deltaLink: previousNextLink,
          })
          .where(eq(directoriesSync.id, syncStats.id))
          .execute();
      }
    }

    traceAttrs({
      delta_query_page_count: pageCount,
      delta_query_should_sync: shouldSyncDirectories,
    });
    this.logger.log({
      userProfileId,
      syncStatsId: syncStats.id,
      pageCount,
      shouldSyncDirectories,
      msg: `Delta query completed`,
    });

    return {
      shouldSyncDirectories,
      deltaLink: directroriesResponse['@odata.deltaLink'] ?? null,
      syncStatsId: syncStats.id,
    };
  }

  private async shouldForceDirectoriesSyncForUser(userProfileId: string): Promise<boolean> {
    const directoryDefinedDuringIngestion = await this.db.query.directories.findMany({
      where: and(
        eq(directories.userProfileId, userProfileId),
        eq(directories.internalType, `Unknown Directory: Created during email ingestion`),
      ),
    });
    if (!directoryDefinedDuringIngestion.length) {
      return false;
    }

    // We mark the directories as user defined imediately to avoid a race condition since we do
    // not execute this in a transaction. We still have a posibility of failure because of some
    // microsoft api failure. We should maybe block this operation differently to ensure
    // the data correctness but for now we want to observe if we are overthinking this issue.
    await this.db
      .update(directories)
      .set({ internalType: 'User Defined Directory' })
      .where(
        and(
          eq(directories.userProfileId, userProfileId),
          inArray(
            directories.id,
            directoryDefinedDuringIngestion.map((item) => item.id),
          ),
        ),
      )
      .execute();
    return true;
  }

  private async findOrCreateStats(userProfileId: string): Promise<DirectoriesSync> {
    let syncStats = await this.db.query.directoriesSync.findFirst({
      where: eq(directoriesSync.userProfileId, userProfileId),
    });

    if (!isNullish(syncStats)) {
      return syncStats;
    }
    await this.db
      .insert(directoriesSync)
      .values({
        userProfileId,
      })
      .onConflictDoNothing()
      .execute();

    syncStats = await this.db.query.directoriesSync.findFirst({
      where: eq(directoriesSync.userProfileId, userProfileId),
    });
    assert.ok(syncStats, `Count not create sync stats for userProfile, ${userProfileId}`);
    return syncStats;
  }
}
