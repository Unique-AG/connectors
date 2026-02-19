import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import { DirectoriesSync, directoriesSync } from '~/db';
import { DRIZZLE, DrizzleDatabase } from '~/db/drizzle.module';
import { traceAttrs, traceEvent } from '~/email-sync/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';
import { graphOutlookDirectoriesDeltaResponse } from './microsoft-graph.dtos';
import { SyncDirectoriesForSubscriptionCommand } from './sync-directories-for-subscription.command';

@Injectable()
export class SyncDirectoriesCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly syncDirectoriesForSubscriptionCommand: SyncDirectoriesForSubscriptionCommand,
  ) {}

  @Span()
  public async run(userProfileTypeId: UserProfileTypeID): Promise<void> {
    traceAttrs({ user_profile_type_id: userProfileTypeId.toString() });
    const userProfile = await this.getUserProfileQuery.run(userProfileTypeId);
    const { shouldSyncDirectories, deltaLink, syncStatsId } = await this.runDeltaQuery(
      userProfile.id,
    );
    traceEvent('delta sync completed', {
      should_sync_directories: shouldSyncDirectories,
    });
    if (shouldSyncDirectories) {
      await this.syncDirectoriesForSubscriptionCommand.run(userProfileTypeId);
    }
    // We do not check the delta link because microsoft returns the same delta link as the current one.
    await this.db
      .update(directoriesSync)
      .set({
        deltaLink,
        lastDeltaSyncRunedAt: new Date(),
      })
      .where(eq(directoriesSync.id, syncStatsId))
      .execute();
  }

  private async runDeltaQuery(userProfileId: string): Promise<{
    shouldSyncDirectories: boolean;
    deltaLink: string | null;
    syncStatsId: string;
  }> {
    const syncStats = await this.findOrCreateStats(userProfileId);

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    let directoriesDeltaResult = await client
      .api(syncStats.deltaLink || `/me/mailFolders/delta`)
      .get();

    let directroriesResponse = graphOutlookDirectoriesDeltaResponse.parse(directoriesDeltaResult);
    let shouldSyncDirectories = false;

    if (directroriesResponse.value.length > 0) {
      shouldSyncDirectories = true;
      await this.db
        .update(directoriesSync)
        .set({ lastDeltaChangeDetectedAt: new Date() })
        .where(eq(directoriesSync.id, syncStats.id))
        .execute();
    }

    while (directroriesResponse['@odata.nextLink']) {
      const previousNextLink = directroriesResponse['@odata.nextLink'];
      directoriesDeltaResult = await client.api(directroriesResponse['@odata.nextLink']).get();
      directroriesResponse = graphOutlookDirectoriesDeltaResponse.parse(directoriesDeltaResult);

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

    return {
      shouldSyncDirectories,
      deltaLink: directroriesResponse['@odata.deltaLink'] ?? null,
      syncStatsId: syncStats.id,
    };
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
