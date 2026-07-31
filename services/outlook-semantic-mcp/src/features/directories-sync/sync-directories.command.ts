import assert from 'node:assert';
import { createSmeared, smearEmail } from '@unique-ag/utils';
import { Client, GraphError } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { Attributes } from '@opentelemetry/api';
import { and, eq, inArray } from 'drizzle-orm';
import { isNonNullish, isNullish } from 'remeda';
import { DirectoriesSync, directories, directoriesSync } from '~/db';
import { DRIZZLE, DrizzleDatabase } from '~/db/drizzle.module';
import { NewTrace, traceAttrs, traceEvent } from '~/features/tracing.utils';
import {
  isNoDelegatesResult,
  MsGraphClientResolver,
} from '~/msgraph/ms-graph-client-resolver.service';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';
import { graphOutlookDirectoriesDeltaResponse } from './microsoft-graph.dtos';
import { SyncDirectoriesForUserProfileCommand } from './sync-directories-for-user-profile.command';

@Injectable()
export class SyncDirectoriesCommand {
  private readonly logger = new Logger(SyncDirectoriesCommand.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly msGraphClientResolver: MsGraphClientResolver,
    private readonly getUserProfileQuery: GetUserProfileQuery,
    private readonly syncDirectoriesForUserProfileCommand: SyncDirectoriesForUserProfileCommand,
  ) {}

  @NewTrace('sync-directories')
  public async run(userProfileId: UserProfileTypeID): Promise<void> {
    traceAttrs({ userProfileId: userProfileId.toString() });
    this.logger.log({
      userProfileId: userProfileId.toString(),
      msg: `Starting directories sync`,
    });

    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    traceAttrs({ userProfileId: userProfile.id });
    const userEmail = smearEmail(createSmeared(userProfile.email));
    this.logger.log({
      userProfileId: userProfile.id,
      userEmail,
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
    traceAttrs({ shouldForceDirectoriesSync: shouldForceDirectoriesSync });
    this.logger.log({
      userProfileId: userProfile.id,
      userEmail,
      shouldForceDirectoriesSync,
      msg: `Checked force sync condition`,
    });

    const syncStats = await this.findOrCreateStats(userProfile.id);
    let activeDelegateUserId: string | undefined;
    const deltaQueryResult = await this.msGraphClientResolver.run({
      userProfile,
      fn: async ({ client, clientUserProfileId }) => {
        activeDelegateUserId = clientUserProfileId;
        const initialDeltaEndpoint =
          userProfile.source === 'shared-mailbox'
            ? `/users/${userProfile.email}/mailFolders/delta`
            : `/me/mailFolders/delta`;
        try {
          return await this.runDeltaQuery(userProfile.id, client, initialDeltaEndpoint, syncStats);
        } catch (err) {
          if (err instanceof GraphError && err.statusCode === 410 && syncStats.deltaLink) {
            // MS Graph returns 410 when a delta token is no longer usable — this happens either
            // because the token expired (tokens are valid for ~7 days of inactivity) or because
            // the delegate who originally obtained it no longer has access to this mailbox.
            // We clear both the delta link and the stored delegate so the retry below starts a
            // full re-sync using whichever delegate the resolver picks now.
            await this.db
              .update(directoriesSync)
              .set({ deltaLink: null, synchronizedByUserProfileId: null })
              .where(eq(directoriesSync.id, syncStats.id))
              .execute();
            return this.runDeltaQuery(userProfile.id, client, initialDeltaEndpoint, {
              ...syncStats,
              deltaLink: null,
              synchronizedByUserProfileId: null,
            });
          }
          throw err;
        }
      },
      sharedMailboxConfig: {
        preferredDelegateUserId: syncStats.synchronizedByUserProfileId ?? undefined,
      },
    });

    if (isNoDelegatesResult(deltaQueryResult)) {
      this.logger.warn({
        userProfileId: userProfile.id,
        userEmail,
        msg: `No delegates found for shared mailbox, skipping directory sync`,
      });
      await this.db
        .update(directoriesSync)
        .set({ lastDeltaSyncRanAt: new Date() })
        .where(eq(directoriesSync.id, syncStats.id))
        .execute();
      return;
    }

    const { shouldSyncDirectories, deltaLink, syncStatsId } = deltaQueryResult;
    traceEvent('delta sync completed', {
      shouldSyncDirectories: shouldSyncDirectories,
      deltaLinkPresent: isNonNullish(deltaLink),
    });
    const logContext: Attributes = {
      userProfileId: userProfile.id,
      userEmail: userEmail.toString(),
      shouldSyncDirectories,
      shouldForceDirectoriesSync,
      syncStatsId,
    };
    traceAttrs({ ...logContext, deltaLinkPresent: isNonNullish(deltaLink) });
    if (shouldSyncDirectories || shouldForceDirectoriesSync) {
      traceEvent(`Run directories sync`);
      this.logger.log({ ...logContext, msg: `Run directories sync` });
      await this.syncDirectoriesForUserProfileCommand.run(userProfileId);
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
        synchronizedByUserProfileId:
          userProfile.source === 'shared-mailbox' ? (activeDelegateUserId ?? null) : null,
      })
      .where(eq(directoriesSync.id, syncStatsId))
      .execute();
    this.logger.log({
      ...logContext,
      deltaLinkPresent: isNonNullish(deltaLink),
      msg: `Updated delta sync stats`,
    });
  }

  private async runDeltaQuery(
    userProfileId: string,
    client: Client,
    initialDeltaEndpoint: string,
    syncStats: DirectoriesSync,
  ): Promise<{
    shouldSyncDirectories: boolean;
    deltaLink: string | null;
    syncStatsId: string;
  }> {
    const isInitialSync = !syncStats.deltaLink;
    traceAttrs({ deltaQueryIsInitialSync: isInitialSync, syncStatsId: syncStats.id });
    this.logger.log({
      userProfileId,
      syncStatsId: syncStats.id,
      isInitialSync,
      msg: `Running delta query`,
    });

    const deltaApi = syncStats.deltaLink
      ? client.api(syncStats.deltaLink)
      : client.api(initialDeltaEndpoint).query({ includeHiddenFolders: 'true' });

    let directoriesDeltaResult = await deltaApi.get();

    let directroriesResponse = graphOutlookDirectoriesDeltaResponse.parse(directoriesDeltaResult);
    let shouldSyncDirectories = false;
    let pageCount = 1;

    if (directroriesResponse.value.length > 0) {
      shouldSyncDirectories = true;
      traceEvent('delta changes detected', {
        page: pageCount,
        changeCount: directroriesResponse.value.length,
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
        changeCount: directroriesResponse.value.length,
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
      deltaQueryPageCount: pageCount,
      deltaQueryShouldSync: shouldSyncDirectories,
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
