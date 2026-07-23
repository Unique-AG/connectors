import { Inject, Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { and, count, countDistinct, eq, inArray, isNotNull, sql } from 'drizzle-orm';
import { alias } from 'drizzle-orm/pg-core';
import {
  DelegatedAccessConfig,
  delegatedAccessConfig,
  IngestionConfig,
  ingestionConfig,
  McpBackendType,
} from '~/config';
import {
  DRIZZLE,
  DrizzleDatabase,
  delegatedAccessAccounts,
  inboxConfigurations,
  userProfiles,
} from '~/db';
import { DISCOVER_DELEGATED_ACCESS_CACHE_KEY } from '~/features/delegated-access/discovery/discover-delegated-access.command';
import { PersistentCacheService } from '~/features/persistent-cache/persistent-cache.service';
import { selectUserProfileIdsWhichCanRunTheSyncProcess } from '~/features/sync/sync-scheduler.utils';
import { FAILED_HEARTBEAT_MINUTES } from '~/features/sync/full-sync/full-sync.command';
import { FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES } from '~/features/sync/live-catch-up/live-catch-up.command';
import { getThreshold } from '~/utils/get-threshold';

@Injectable()
export class McpProcessesHealthIndicator {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(ingestionConfig.KEY) private readonly ingestionCfg: IngestionConfig,
    @Inject(delegatedAccessConfig.KEY) private readonly delegatedAccessCfg: DelegatedAccessConfig,
    private readonly healthIndicatorService: HealthIndicatorService,
    private readonly persistentCacheService: PersistentCacheService,
  ) {}

  public async checkFullSync(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    if (this.ingestionCfg.mcpBackend !== McpBackendType.MicrosoftGraphAndUniqueApi) {
      throw new Error('checkFullSync requires MicrosoftGraphAndUniqueApi backend');
    }
    const { syncFailureThreshold } = this.ingestionCfg;
    const heartbeatThreshold = getThreshold(FAILED_HEARTBEAT_MINUTES);

    const [row] = await this.db
      .select({
        totalEligible: count(),
        failing: sql<number>`COALESCE(SUM(CASE
          WHEN ${inboxConfigurations.fullSyncState} = 'failed'
            AND ${inboxConfigurations.fullSyncHeartbeatAt} < ${heartbeatThreshold}
          THEN 1 ELSE 0 END), 0)`,
      })
      .from(inboxConfigurations)
      .where(
        inArray(
          inboxConfigurations.userProfileId,
          selectUserProfileIdsWhichCanRunTheSyncProcess(this.db),
        ),
      );

    const eligible = row?.totalEligible ?? 0;
    const failing = Number(row?.failing ?? 0);
    const ratio = eligible > 0 ? failing / eligible : 0;

    const details = {
      threshold: syncFailureThreshold,
      eligibleUsers: eligible,
      failingUsers: failing,
      ratio,
    };
    return ratio > syncFailureThreshold ? indicator.down(details) : indicator.up(details);
  }

  public async checkLiveCatchup(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    if (this.ingestionCfg.mcpBackend !== McpBackendType.MicrosoftGraphAndUniqueApi) {
      throw new Error('checkLiveCatchup requires MicrosoftGraphAndUniqueApi backend');
    }
    const { syncFailureThreshold } = this.ingestionCfg;
    const heartbeatThreshold = getThreshold(FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES);

    const [row] = await this.db
      .select({
        totalEligible: count(),
        failing: sql<number>`COALESCE(SUM(CASE
          WHEN ${inboxConfigurations.liveCatchUpState} = 'failed'
            AND ${inboxConfigurations.liveCatchUpHeartbeatAt} < ${heartbeatThreshold}
          THEN 1 ELSE 0 END), 0)`,
      })
      .from(inboxConfigurations)
      .where(
        inArray(
          inboxConfigurations.userProfileId,
          selectUserProfileIdsWhichCanRunTheSyncProcess(this.db),
        ),
      );

    const eligible = row?.totalEligible ?? 0;
    const failing = Number(row?.failing ?? 0);
    const ratio = eligible > 0 ? failing / eligible : 0;

    const details = {
      threshold: syncFailureThreshold,
      eligibleUsers: eligible,
      failingUsers: failing,
      ratio,
    };
    return ratio > syncFailureThreshold ? indicator.down(details) : indicator.up(details);
  }

  public async checkDelegatedAccess(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);
    if (this.delegatedAccessCfg.scan === 'disabled') {
      throw new Error('checkDelegatedAccess requires delegated access to be enabled');
    }
    const { failureThreshold, stalenessThresholdHours } = this.delegatedAccessCfg;
    const stalenessThreshold = sql`NOW() - (${stalenessThresholdHours} * INTERVAL '1 hour')`;

    // Count Microsoft access tokens on the delegate's own user profile, not the MCP
    // OAuth-provider tokens in the `tokens` table (which are unrelated to Graph auth).
    const delegateProfiles = alias(userProfiles, 'delegate_profiles');
    const [row] = await this.db
      .select({
        totalDelegated: countDistinct(delegatedAccessAccounts.delegateUserId),
        stale: sql<number>`COUNT(DISTINCT CASE
          WHEN ${delegatedAccessAccounts.lastVerifiedAt} IS NULL
            OR ${delegatedAccessAccounts.lastVerifiedAt} < ${stalenessThreshold}
          THEN ${delegatedAccessAccounts.delegateUserId}
        END)`,
        withValidAccessToken: sql<number>`COUNT(DISTINCT ${delegateProfiles.id})`,
      })
      .from(delegatedAccessAccounts)
      .leftJoin(
        delegateProfiles,
        and(
          eq(delegateProfiles.id, delegatedAccessAccounts.delegateUserId),
          isNotNull(delegateProfiles.accessToken),
        ),
      )
      .where(inArray(delegatedAccessAccounts.delegateUserId, this.usersWithValidTokenSubquery()));

    const total = row?.totalDelegated ?? 0;
    const stale = Number(row?.stale ?? 0);
    const withValidAccessToken = Number(row?.withValidAccessToken ?? 0);
    const ratio = total > 0 ? stale / total : 0;

    const scan = await this.persistentCacheService.get(
      DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
      'DelegatedAccessDiscovery',
    );
    const lastProgressRegisteredAt = scan?.payload.lastProgressRegisteredAt;

    const details = {
      threshold: failureThreshold,
      eligibleUsers: total,
      failingUsers: stale,
      usersWithValidAccessToken: withValidAccessToken,
      ratio,
      scanStatus: scan?.payload.state ?? 'unknown',
      scanLastRunAt: lastProgressRegisteredAt
        ? new Date(lastProgressRegisteredAt).toISOString()
        : null,
    };
    return ratio > failureThreshold ? indicator.down(details) : indicator.up(details);
  }

  private usersWithValidTokenSubquery() {
    // Mirrors the delegate candidate set in DiscoverDelegatedAccessCommand.fetchBatch:
    // delegates are always OAuth profiles that hold an access token.
    return this.db
      .selectDistinct({ userProfileId: userProfiles.id })
      .from(userProfiles)
      .where(and(eq(userProfiles.source, 'oauth'), isNotNull(userProfiles.accessToken)));
  }
}
