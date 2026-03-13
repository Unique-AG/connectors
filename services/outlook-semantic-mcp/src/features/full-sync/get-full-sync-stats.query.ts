import { IngestionState, UniqueApiClient } from '@unique-ag/unique-api';
import { asAllOptions } from '@unique-ag/utils';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { omit, sumBy, values } from 'remeda';
import z from 'zod';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, UserProfile } from '~/db';
import { inboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { getRootScopeExternalIdForUser } from '~/unique/get-root-scope-path';
import { InjectUniqueApi } from '~/unique/unique-api.module';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '~/utils/non-nullish-props';
import { GetUserProfileQuery } from '../user-utils/get-user-profile.query';

const ingestionStatsError = z.object({
  state: z
    .enum(['error'])
    .describe(
      '"error" means all eighter your inbox connection is somehow broken we cannot find your root scope. Or calling ingestion failed see "errorMessage" property for details',
    ),
  message: z.string(),
});
const ingestionStateSuccess = z.object({
  state: z
    .enum(['finished', 'running'])
    .describe(
      '"finished" means all queued emails have been ingested, "running" means ingestion is still in progress.',
    ),
  failed: z.number().describe('Number of emails that failed ingestion.'),
  finished: z.number().describe('Number of emails successfully ingested into the vector store.'),
  inProgress: z.number().describe('Number of emails currently being ingested.'),
});

const ingestionStats = z.discriminatedUnion('state', [ingestionStateSuccess, ingestionStatsError]);

export const GetFullSyncStatsResponse = z.object({
  state: z.enum(['error', 'running', 'finished']),
  message: z.string(),
  syncStats: z
    .object({
      fullSyncState: z.enum(['ready', 'failed', 'fetching-emails']),
      liveCatchUpState: z.enum(['ready', 'running', 'failed']),
      runAt: z.string().nullable(),
      startedAt: z.string().nullable(),
      filters: z.object({
        ignoredBefore: z.string().nullable(),
        ignoredSenders: z.array(z.string()),
        ignoredContents: z.array(z.string()),
      }),
      dateWindow: z.object({
        newestCreatedDateTime: z.string().nullable(),
        oldestCreatedDateTime: z.string().nullable(),
        newestLastModifiedDateTime: z.string().nullable(),
        oldestLastModifiedDateTime: z.string().nullable(),
      }),
    })
    .nullable(),
  ingestionStats: ingestionStats.nullable(),
});

type FullSyncStats = z.infer<typeof GetFullSyncStatsResponse>;

type FailedIngestionStates = Exclude<
  IngestionState,
  | IngestionState.CheckingIntegrity
  | IngestionState.Finished
  | IngestionState.IngestionChunking
  | IngestionState.IngestionEmbedding
  | IngestionState.IngestionReading
  | IngestionState.MalwareScanning
  | IngestionState.MetadataValidation
  | IngestionState.Queued
  | IngestionState.RebuildingMetadata
  | IngestionState.RecreatingVecetordbIndex
  | IngestionState.Retrying
  | IngestionState.ReEmbedding
  | IngestionState.ReIngesting
  | IngestionState.ExtractingMetadata
>;

const FAILED_INGESTION_STATUSES = asAllOptions<FailedIngestionStates>()([
  IngestionState.Failed,
  IngestionState.FailedCreatingChunks,
  IngestionState.FailedEmbedding,
  IngestionState.FailedGettingFile,
  IngestionState.FailedImage,
  IngestionState.FailedMalwareFound,
  IngestionState.FailedMetadataValidation,
  IngestionState.FailedMalwareScanTimeout,
  IngestionState.FailedParsing,
  IngestionState.FailedRedelivered,
  IngestionState.FailedTimeout,
  IngestionState.FailedTooLessContent,
  IngestionState.FailedTableLimitExceeded,
]);

@Injectable()
export class GetFullSyncStatsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @InjectUniqueApi() private readonly uniqueApi: UniqueApiClient,
    private getUserProfileQuery: GetUserProfileQuery,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<FullSyncStats> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const inboxConfig = await this.db.query.inboxConfiguration.findFirst({
      where: eq(inboxConfiguration.userProfileId, userProfile.id),
    });
    if (!inboxConfig) {
      return {
        state: 'error',
        syncStats: null,
        ingestionStats: null,
        message: `Your inbox is disconnected. Use \`reconnect_inbox\` tool to reconnect`,
      };
    }
    if (inboxConfig.fullSyncState === 'failed') {
      return {
        state: 'error',
        syncStats: null,
        ingestionStats: null,
        message: `Full sync failed. Use \`run_full_sync\` tool to sync your inbox`,
      };
    }
    if (inboxConfig.liveCatchUpState === 'failed') {
      return {
        state: 'error',
        syncStats: null,
        ingestionStats: null,
        message: `Live catch-up failed. Use \`run_full_sync\` tool to sync your inbox`,
      };
    }
    const ingestionResult = await this.getIngestionStats(userProfile);
    if (ingestionResult.state === 'error') {
      return {
        state: 'error',
        syncStats: null,
        ingestionStats: null,
        message: ingestionResult.message,
      };
    }
    const filters = inboxConfigurationMailFilters.parse(inboxConfig.filters);

    const syncStats = {
      fullSyncState: inboxConfig.fullSyncState,
      liveCatchUpState: inboxConfig.liveCatchUpState,
      runAt: inboxConfig.lastFullSyncRunAt?.toISOString() ?? null,
      startedAt: inboxConfig.lastFullSyncStartedAt?.toISOString() ?? null,
      filters: {
        ignoredBefore: filters.ignoredBefore.toISOString() ?? null,
        ignoredSenders: filters.ignoredSenders.map((r) => r.toString()),
        ignoredContents: filters.ignoredContents.map((r) => r.toString()),
      },
      dateWindow: {
        newestCreatedDateTime: inboxConfig.newestCreatedDateTime?.toISOString() ?? null,
        oldestCreatedDateTime: inboxConfig.oldestCreatedDateTime?.toISOString() ?? null,
        newestLastModifiedDateTime: inboxConfig.newestLastModifiedDateTime?.toISOString() ?? null,
        oldestLastModifiedDateTime: inboxConfig.oldestLastModifiedDateTime?.toISOString() ?? null,
      },
    };

    const isRunning =
      inboxConfig.fullSyncState !== 'ready' ||
      inboxConfig.liveCatchUpState !== 'ready' ||
      ingestionResult.inProgress > 0;

    return {
      message: ``,
      ingestionStats: ingestionResult,
      syncStats,
      state: isRunning ? 'running' : 'finished',
    };
  }

  private async getIngestionStats(
    userProfile: NonNullishProps<UserProfile, 'email'>,
  ): Promise<z.infer<typeof ingestionStats>> {
    const userProfileId = userProfile.id;

    try {
      const rootScopeId = getRootScopeExternalIdForUser(userProfile.providerUserId);
      const rootScope = await this.uniqueApi.scopes.getByExternalId(rootScopeId);
      if (!rootScope) {
        this.logger.debug({ userProfileId, msg: 'Root scope is missing' });
        return {
          state: 'error',
          message: `Could not find root scope, please reconnect your inbox`,
        };
      }
      const ingestionStats = await this.uniqueApi.ingestion.getIngestionStats(rootScope.id);

      this.logger.debug({ userProfileId, msg: 'Full sync progress retrieved' });

      const failed = sumBy(FAILED_INGESTION_STATUSES, (status) => ingestionStats[status] ?? 0);
      const finished = ingestionStats.FINISHED ?? 0;
      const inProgress = sumBy(
        values(omit(ingestionStats, [...FAILED_INGESTION_STATUSES, IngestionState.Finished])),
        (item) => item ?? 0,
      );

      return { failed, finished, inProgress, state: inProgress > 0 ? 'running' : 'finished' };
    } catch (error) {
      this.logger.warn({
        userProfileId,
        msg: 'Failed to fetch ingestion stats from Unique API',
        error,
      });
      return {
        state: 'error',
        message: `Ingestion service is not reachable`,
      };
    }
  }
}
