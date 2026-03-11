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

const ingestionKnwonState = z.object({
  state: z.enum(['idle', 'running']).describe('"idle" means all queued emails have been ingested, "running" means ingestion is still in progress.'),
  failed: z.number().describe('Number of emails that failed ingestion.'),
  finished: z.number().describe('Number of emails successfully ingested into the vector store.'),
  inProgress: z.number().describe('Number of emails currently being ingested.'),
});

const ingestionUnknownState = z.object({
  state: z.enum(['unknown']).describe('Ingestion stats could not be retrieved from the Unique API.'),
  failed: z.null(),
  finished: z.null(),
  inProgress: z.null(),
});

const ingestionStats = z.discriminatedUnion('state', [ingestionUnknownState, ingestionKnwonState]);

const toQueueForIngestionKnwonState = z.object({
  state: z.enum(['idle', 'running', 'failed']).describe('"idle" means the fetch-and-queue phase is complete, "running" means it is in progress, "failed" means it encountered an error.'),
  runAt: z.string().nullable().describe('ISO timestamp of when the last full sync run was scheduled, or null if not yet run.'),
  startedAt: z.string().nullable().describe('ISO timestamp of when the last full sync run started, or null if not yet started.'),
  filters: z.object({
    ignoredBefore: z.iso.datetime().nullable().describe('Emails received before this timestamp are excluded from sync. Null means no date filter is applied.'),
    ignoredSenders: z.array(z.string()).describe('Regex patterns (as strings) matched against the sender email address. Emails matching any pattern are excluded from sync.'),
    ignoredContents: z.array(z.string()).describe('Regex patterns (as strings) matched against the email subject and body. Emails matching any pattern are excluded from sync.'),
  }),
  messages: z.object({
    received: z.number().describe('Total number of emails received from Microsoft during the sync.'),
    queuedForSync: z.number().describe('Number of emails queued for ingestion into the vector store.'),
    processed: z.number().describe('Number of emails that have been processed (handed off for ingestion).'),
  }),
});

const toQueueForIngestionUnknownState = z.object({
  state: z.enum(['unknown']).describe('The inbox configuration could not be found; sync state is unknown.'),
  runAt: z.null(),
  startedAt: z.null(),
  filters: z.null(),
  messages: z.object({
    received: z.null(),
    queuedForSync: z.null(),
    processed: z.null(),
  }),
});

const toQueueForIngestionSchema = z.discriminatedUnion('state', [
  toQueueForIngestionKnwonState,
  toQueueForIngestionUnknownState,
]);

export const GetFullSyncStatsResponse = z.object({
  state: z
    .enum(['idle', 'running', 'unknown'])
    .describe(
      'Overall sync state. "idle" means sync is complete, "running" means sync is in progress and results may be incomplete, "unknown" means the inbox connection could not be found.',
    ),
  progressPercentage: z
    .number()
    .nullable()
    .describe('Overall sync progress as a percentage (0–100), or null when state is "unknown".'),
  toQueueForIngestionStats: toQueueForIngestionSchema.describe(
    'Stats for the phase that fetches emails from Microsoft and queues them for ingestion.',
  ),
  ingestionStats: ingestionStats.describe(
    'Stats for the phase that ingests queued emails into the vector store.',
  ),
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
    const config = await this.db.query.inboxConfiguration.findFirst({
      where: eq(inboxConfiguration.userProfileId, userProfile.id),
    });
    const ingestionStats = await this.getIngestionStats(userProfile);
    const filters = config ? inboxConfigurationMailFilters.parse(config.filters) : null;

    const toQueueForIngestionStats: z.Infer<typeof toQueueForIngestionSchema> = config
      ? {
          state: config.syncState,
          runAt: config.lastFullSyncRunAt?.toISOString() ?? null,
          startedAt: config.syncStartedAt?.toISOString() ?? null,
          filters: {
            ignoredBefore: filters?.ignoredBefore.toISOString() ?? null,
            ignoredSenders: filters?.ignoredSenders.map((r) => r.toString()) ?? [],
            ignoredContents: filters?.ignoredContents.map((r) => r.toString()) ?? [],
          },
          messages: {
            received: config.messagesFromMicrosoft,
            queuedForSync: config.messagesQueuedForSync,
            processed: config.messagesProcessed,
          },
        }
      : {
          state: 'unknown',
          runAt: null,
          startedAt: null,
          filters: null,
          messages: {
            received: null,
            queuedForSync: null,
            processed: null,
          },
        };

    if (toQueueForIngestionStats.state === 'unknown' && ingestionStats.state === 'unknown') {
      return {
        toQueueForIngestionStats,
        ingestionStats,
        state: 'unknown',
        progressPercentage: null,
      };
    }

    if (toQueueForIngestionStats.state !== 'unknown' && ingestionStats.state !== 'unknown') {
      const isRunning =
        toQueueForIngestionStats.state === 'running' ||
        ingestionStats.state === 'running' ||
        toQueueForIngestionStats.messages.processed <
          toQueueForIngestionStats.messages.queuedForSync;

      if (!isRunning) {
        return { ingestionStats, toQueueForIngestionStats, state: 'idle', progressPercentage: 100 };
      }

      // We intentionally double count the messages because ingestion is the slow operation
      // probably we will have 50% progress pretty fast but the rest will slowly go until
      // ingestion finishes.
      const totalCount =
        toQueueForIngestionStats.messages.queuedForSync +
        ingestionStats.inProgress +
        ingestionStats.failed +
        ingestionStats.finished;
      const completedCount =
        toQueueForIngestionStats.messages.processed +
        ingestionStats.finished +
        ingestionStats.failed;

      const progressPercentage =
        totalCount === 0 ? 100 : Number(((completedCount / totalCount) * 100).toFixed(2));

      return { ingestionStats, toQueueForIngestionStats, state: 'running', progressPercentage };
    }

    return {
      ingestionStats,
      toQueueForIngestionStats,
      state:
        toQueueForIngestionStats.state !== 'unknown' || ingestionStats.state !== 'unknown'
          ? 'running'
          : 'idle',
      progressPercentage: null,
    };
  }

  private async getIngestionStats(
    userProfile: NonNullishProps<UserProfile, 'email'>,
  ): Promise<z.infer<typeof ingestionStats>> {
    const userProfileId = userProfile.id;
    const unknownState = {
      failed: null,
      finished: null,
      inProgress: null,
      state: 'unknown',
    } as const;

    try {
      const rootScopeId = getRootScopeExternalIdForUser(userProfile.providerUserId);
      const rootScope = await this.uniqueApi.scopes.getByExternalId(rootScopeId);
      if (!rootScope) {
        this.logger.debug({ userProfileId, msg: 'Root scope is missing' });
        return unknownState;
      }
      const ingestionStats = await this.uniqueApi.ingestion.getIngestionStats(rootScope.id);

      this.logger.debug({ userProfileId, msg: 'Full sync progress retrieved' });

      const failed = sumBy(FAILED_INGESTION_STATUSES, (status) => ingestionStats[status] ?? 0);
      const finished = ingestionStats.FINISHED ?? 0;
      const inProgress = sumBy(
        values(omit(ingestionStats, [...FAILED_INGESTION_STATUSES, IngestionState.Finished])),
        (item) => item ?? 0,
      );

      return { failed, finished, inProgress, state: inProgress > 0 ? 'running' : 'idle' };
    } catch (error) {
      this.logger.warn({
        userProfileId,
        msg: 'Failed to fetch ingestion stats from Unique API',
        error,
      });
      return unknownState;
    }
  }
}
