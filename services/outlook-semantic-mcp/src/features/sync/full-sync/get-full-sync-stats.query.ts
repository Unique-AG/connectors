import { Inject, Injectable, Logger } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import z from 'zod';
import { AppConfig, appConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { inboxConfigurationMailFilters } from '~/db/schema/inbox/inbox-configuration-mail-filters.dto';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { GetUserProfileQuery } from '../../user-utils/get-user-profile.query';
import { GetScopeIngestionStatsQuery } from './get-scope-ingestion-stats.query';

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
      fullSyncState: z.enum(['ready', 'failed', 'running', 'paused', 'waiting-for-ingestion']),
      liveCatchUpState: z.enum(['ready', 'running', 'failed']),
      runAt: z.string().nullable(),
      startedAt: z.string().nullable(),
      filters: z.object({
        ignoredBefore: z.string().nullable(),
        ignoredSenders: z.array(z.string()),
        ignoredContents: z.array(z.string()),
      }),
      expectedTotal: z
        .number()
        .nullable()
        .describe('Total message count from $count API call at sync start.'),
      skippedMessages: z.number().describe('Messages filtered out by sender/content/date rules.'),
      scheduledForIngestion: z.number().describe('Messages successfully submitted for ingestion.'),
      failedToUploadForIngestion: z
        .number()
        .describe('Messages that failed upload after 3 retries.'),
      dateWindow: z.object({
        newestCreatedDateTime: z.string().nullable(),
        oldestCreatedDateTime: z.string().nullable(),
        newestLastModifiedDateTime: z.string().nullable(),
      }),
    })
    .nullable(),
  ingestionStats: ingestionStats.nullable(),
  debugData: z
    .object({
      providerUserId: z.string().nullable().optional(),
      userProfileId: z.string().nullable().optional(),
      subscriptionId: z.string().nullable().optional(),
    })
    .optional(),
});

type FullSyncStats = z.infer<typeof GetFullSyncStatsResponse>;

@Injectable()
export class GetFullSyncStatsQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
    private getUserProfileQuery: GetUserProfileQuery,
    private getScopeIngestionStats: GetScopeIngestionStatsQuery,
  ) {}

  @Span()
  public async run(userProfileId: UserProfileTypeID): Promise<FullSyncStats> {
    const userProfile = await this.getUserProfileQuery.run(userProfileId);
    const inboxConfig = await this.db.query.inboxConfiguration.findFirst({
      where: eq(inboxConfiguration.userProfileId, userProfile.id),
    });
    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.userProfileId, userProfile.id),
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
    const ingestionResult = await this.getIngestionStats(userProfile.id);
    if (ingestionResult.state === 'error') {
      return {
        state: 'error',
        syncStats: null,
        ingestionStats: null,
        message: ingestionResult.message,
      };
    }
    const filters = inboxConfigurationMailFilters.parse(inboxConfig.filters);
    const debugData = {
      providerUserId: userProfile.providerUserId,
      userProfileId: userProfile.id,
      subscriptionId: subscription?.id,
    };

    const syncStats = {
      fullSyncState: inboxConfig.fullSyncState,
      liveCatchUpState: inboxConfig.liveCatchUpState,
      runAt: inboxConfig.fullSyncLastRunAt?.toISOString() ?? null,
      startedAt: inboxConfig.fullSyncLastStartedAt?.toISOString() ?? null,
      expectedTotal: inboxConfig.fullSyncExpectedTotal ?? null,
      skippedMessages: inboxConfig.fullSyncSkipped,
      scheduledForIngestion: inboxConfig.fullSyncScheduledForIngestion,
      failedToUploadForIngestion: inboxConfig.fullSyncFailedToUploadForIngestion,
      filters: {
        ignoredBefore: filters.ignoredBefore.toISOString() ?? null,
        ignoredSenders: filters.ignoredSenders.map((r) => r.toString()),
        ignoredContents: filters.ignoredContents.map((r) => r.toString()),
      },
      dateWindow: {
        newestCreatedDateTime: inboxConfig.newestCreatedDateTime?.toISOString() ?? null,
        oldestCreatedDateTime: inboxConfig.oldestCreatedDateTime?.toISOString() ?? null,
        newestLastModifiedDateTime: inboxConfig.newestLastModifiedDateTime?.toISOString() ?? null,
      },
    };

    const isRunning =
      inboxConfig.fullSyncState !== 'ready' ||
      inboxConfig.liveCatchUpState !== 'ready' ||
      ingestionResult.inProgress > 0;

    return {
      message: `Stats retrieved succesfully`,
      ingestionStats: ingestionResult,
      syncStats,
      debugData: this.config.mcpDebugMode ? debugData : undefined,
      state: isRunning ? 'running' : 'finished',
    };
  }

  private async getIngestionStats(userProfileId: string): Promise<z.infer<typeof ingestionStats>> {
    const result = await this.getScopeIngestionStats.run(userProfileId);

    if (!result.ok) {
      const message =
        result.reason === 'no-root-scope'
          ? 'Could not find root scope, please reconnect your inbox'
          : 'Ingestion service is not reachable';
      this.logger.debug({
        userProfileId,
        reason: result.reason,
        msg: 'Ingestion stats unavailable',
      });
      return { state: 'error', message };
    }

    this.logger.debug({ userProfileId, msg: 'Full sync progress retrieved' });

    return {
      failed: result.failed,
      finished: result.finished,
      inProgress: result.inProgress,
      state: result.inProgress > 0 ? 'running' : 'finished',
    };
  }
}
