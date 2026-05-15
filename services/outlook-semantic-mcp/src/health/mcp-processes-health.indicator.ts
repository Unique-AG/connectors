import { Inject, Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { and, count, countDistinct, eq, gt, inArray, sql } from 'drizzle-orm';
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
  subscriptions,
  tokens,
} from '~/db';
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
      .where(inArray(inboxConfigurations.userProfileId, this.eligibleSubquery()));

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
      .where(inArray(inboxConfigurations.userProfileId, this.eligibleSubquery()));

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

    const [row] = await this.db
      .select({
        totalDelegated: countDistinct(delegatedAccessAccounts.delegateUserId),
        stale: sql<number>`COUNT(DISTINCT CASE
          WHEN ${delegatedAccessAccounts.lastVerifiedAt} IS NULL
            OR ${delegatedAccessAccounts.lastVerifiedAt} < ${stalenessThreshold}
          THEN ${delegatedAccessAccounts.delegateUserId}
        END)`,
      })
      .from(delegatedAccessAccounts)
      .where(inArray(delegatedAccessAccounts.delegateUserId, this.eligibleSubquery()));

    const total = row?.totalDelegated ?? 0;
    const stale = Number(row?.stale ?? 0);
    const ratio = total > 0 ? stale / total : 0;

    const details = {
      threshold: failureThreshold,
      eligibleUsers: total,
      failingUsers: stale,
      ratio,
    };
    return ratio > failureThreshold ? indicator.down(details) : indicator.up(details);
  }

  private eligibleSubquery() {
    return this.db
      .selectDistinct({ userProfileId: inboxConfigurations.userProfileId })
      .from(inboxConfigurations)
      .innerJoin(
        tokens,
        and(
          eq(tokens.userProfileId, inboxConfigurations.userProfileId),
          eq(tokens.type, 'REFRESH'),
          gt(tokens.expiresAt, sql`NOW()`),
        ),
      )
      .innerJoin(
        subscriptions,
        and(
          eq(subscriptions.userProfileId, inboxConfigurations.userProfileId),
          gt(subscriptions.expiresAt, sql`NOW()`),
        ),
      );
  }
}
