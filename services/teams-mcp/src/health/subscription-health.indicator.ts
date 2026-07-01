import { Inject, Injectable } from '@nestjs/common';
import { HealthIndicatorResult, HealthIndicatorService } from '@nestjs/terminus';
import { count, sql } from 'drizzle-orm';
import { HealthConfig, healthConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/drizzle';

// Subscriptions are renewed daily (see TranscriptUtilsService.getNextScheduledExpiration), with a
// 2-hour lifecycle buffer required before expiry. Anything inside that window is "expiring soon" —
// an observability-only signal that does not by itself trip the indicator to `down`.
const EXPIRING_SOON_THRESHOLD_MINUTES = 120;

@Injectable()
export class SubscriptionHealthIndicator {
  private readonly expiredThreshold: number;

  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(healthConfig.KEY) config: HealthConfig,
    private readonly healthIndicatorService: HealthIndicatorService,
  ) {
    this.expiredThreshold = config.subscriptionExpiredThreshold;
  }

  public async check(key: string): Promise<HealthIndicatorResult> {
    const indicator = this.healthIndicatorService.check(key);

    try {
      const soonThreshold = sql`NOW() + (${EXPIRING_SOON_THRESHOLD_MINUTES} * INTERVAL '1 minute')`;
      const [row] = await this.db
        .select({
          total: count(),
          expired: sql<number>`COALESCE(SUM(CASE
            WHEN ${subscriptions.expiresAt} < NOW() THEN 1 ELSE 0 END), 0)`,
          expiringSoon: sql<number>`COALESCE(SUM(CASE
            WHEN ${subscriptions.expiresAt} >= NOW() AND ${subscriptions.expiresAt} < ${soonThreshold}
            THEN 1 ELSE 0 END), 0)`,
        })
        .from(subscriptions);

      const total = row?.total ?? 0;
      const expired = Number(row?.expired ?? 0);
      const expiringSoon = Number(row?.expiringSoon ?? 0);
      const ratio = total > 0 ? expired / total : 0;

      const details = {
        total,
        expired,
        expiringSoon,
        threshold: this.expiredThreshold,
        ratio,
      };

      return ratio > this.expiredThreshold ? indicator.down(details) : indicator.up(details);
    } catch (error) {
      return indicator.down({ message: error instanceof Error ? error.message : String(error) });
    }
  }
}
