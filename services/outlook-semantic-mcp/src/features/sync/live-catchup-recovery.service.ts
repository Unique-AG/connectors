import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, gt, lt, notInArray, or, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { traceEvent } from '~/features/tracing.utils';
import { LiveCatchUpEventDto } from './live-catch-up/live-catch-up-event.dto';

const STUCK_LIVE_CATCHUP_THRESHOLD_MINUTES = 5;
const RECOVERY_CRON_SCHEDULE = '*/5 * * * *';

@Injectable()
export class LiveCatchupRecoveryService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    this.logger.log({ msg: 'LiveCatchupRecoveryService is shutting down...' });
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob('live-catchup-recovery');
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping live-catchup-recovery cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(RECOVERY_CRON_SCHEDULE, () => {
      void this.runRecoveryScan();
    });

    this.schedulerRegistry.addCronJob('live-catchup-recovery', job);
    job.start();
  }

  public async runRecoveryScan(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping live catchup recovery scan due to shutdown' });
      return;
    }

    try {
      this.logger.log({ msg: 'Live catchup recovery scan triggered' });

      await this.recoverStuckLiveCatchUps();
    } catch (err) {
      this.logger.error({
        msg: 'An unexpected error occurred during live catchup recovery scan',
        err,
      });
    }
  }

  private async recoverStuckLiveCatchUps(): Promise<void> {
    const stuckConfigs = await this.db
      .select({ userProfileId: inboxConfiguration.userProfileId })
      .from(inboxConfiguration)
      .innerJoin(
        subscriptions,
        and(
          eq(subscriptions.userProfileId, inboxConfiguration.userProfileId),
          gt(subscriptions.expiresAt, sql`NOW()`),
        ),
      )
      .where(
        or(
          eq(inboxConfiguration.liveCatchUpState, 'failed'),
          and(
            notInArray(inboxConfiguration.liveCatchUpState, ['ready']),
            lt(
              sql`COALESCE(${inboxConfiguration.liveCatchUpHeartbeatAt}, '-infinity'::timestamptz)`,
              sql`NOW() - ${STUCK_LIVE_CATCHUP_THRESHOLD_MINUTES} * INTERVAL '1 minute'`,
            ),
          ),
        ),
      );

    if (stuckConfigs.length === 0) {
      return;
    }

    traceEvent('live-catch-up stuck recovery triggered', {
      count: stuckConfigs.length,
      userProfileIds: stuckConfigs.map((c) => c.userProfileId),
    });

    this.logger.log({
      msg: 'Found stuck live catch-up configurations',
      count: stuckConfigs.length,
    });

    for (const { userProfileId } of stuckConfigs) {
      this.logger.log({
        msg: 'Publishing live catch-up recovery event',
        userProfileId,
      });
      const event = LiveCatchUpEventDto.parse({
        type: 'unique.outlook-semantic-mcp.live-catch-up.recovery',
        payload: { userProfileId },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    }
  }
}
