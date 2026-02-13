import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { isNullish } from 'remeda';
import { DirectoriesSync, directoriesSync } from '~/drizzle';
import { DRIZZLE, DrizzleDatabase } from '~/drizzle/drizzle.module';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { GetSubscriptionAndUserProfileQuery } from '../subscription-utils/get-subscription-and-user-profile.query';
import { graphOutlookDirectoriesDeltaResponse } from './microsoft-graph.dtos';
import { SyncDirectoriesCommand } from './sync-directories.command';

@Injectable()
export class SyncDirectoriesWithDeltaCommand {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly getSubscriptionAndUserProfileQuery: GetSubscriptionAndUserProfileQuery,
    private readonly syncDirectoriesCommand: SyncDirectoriesCommand,
  ) {}

  @Span()
  public async run(subscriptionId: string): Promise<void> {
    const { userProfile } = await this.getSubscriptionAndUserProfileQuery.run(subscriptionId);
    const { shouldSyncDirectories } = await this.runDeltaQuery(userProfile.id);
    if (shouldSyncDirectories) {
      await this.syncDirectoriesCommand.run(userProfile.id);
    }
  }

  private async runDeltaQuery(userProfileId: string): Promise<{ shouldSyncDirectories: boolean }> {
    const syncStats = await this.findOrCreateStats(userProfileId);

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    let deltaLink = syncStats.deltaLink ?? `/me/mailFolders/delta`;

    let directoriesDeltaResult = await client
      .api(syncStats.deltaLink ?? `/me/mailFolders/delta`)
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
      deltaLink = directroriesResponse['@odata.nextLink'];
      await this.db
        .update(directoriesSync)
        .set({ deltaLink: deltaLink })
        .where(eq(directoriesSync.id, syncStats.id))
        .execute();
      directoriesDeltaResult = await client.api(directroriesResponse['@odata.nextLink']).get();
      directroriesResponse = graphOutlookDirectoriesDeltaResponse.parse(directoriesDeltaResult);
    }

    // We do not check the delta link because microsoft returns the same delta link as the current one.
    await this.db
      .update(directoriesSync)
      .set({
        deltaLink: directroriesResponse['@odata.deltaLink'],
        lastDeltaSyncRunedAt: new Date(),
      })
      .where(eq(directoriesSync.id, syncStats.id))
      .execute();

    return { shouldSyncDirectories };
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
