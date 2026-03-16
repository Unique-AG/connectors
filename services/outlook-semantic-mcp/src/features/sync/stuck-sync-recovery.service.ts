import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, lt, notInArray, or, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { traceEvent } from '~/features/tracing.utils';
import { FullSyncEventDto } from './full-sync/full-sync-event.dto';
import { LiveCatchUpEventDto } from './live-catch-up/live-catch-up-event.dto';

const STUCK_FULL_SYNC_THRESHOLD_MINUTES = 15;
const STUCK_LIVE_CATCHUP_THRESHOLD_MINUTES = 5;
const RECOVERY_CRON_SCHEDULE = '*/5 * * * *';

@Injectable()
export class StuckSyncRecoveryService implements OnModuleInit, OnModuleDestroy {
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
    this.logger.log({ msg: 'StuckSyncRecoveryService is shutting down...' });
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob('stuck-sync-recovery');
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping stuck-sync-recovery cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(RECOVERY_CRON_SCHEDULE, () => {
      void this.runRecoveryScan();
    });

    this.schedulerRegistry.addCronJob('stuck-sync-recovery', job);
    job.start();
  }

  public async runRecoveryScan(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping stuck sync recovery scan due to shutdown' });
      return;
    }

    try {
      this.logger.log({ msg: 'Stuck sync recovery scan triggered' });

      await Promise.all([this.recoverStuckFullSyncs(), this.recoverStuckLiveCatchUps()]);
    } catch (err) {
      this.logger.error({
        msg: 'An unexpected error occurred during stuck sync recovery scan',
        err,
      });
    }
  }

  private async recoverStuckFullSyncs(): Promise<void> {
    const stuckConfigs = await this.db
      .select({ userProfileId: inboxConfiguration.userProfileId })
      .from(inboxConfiguration)
      .where(
        or(
          eq(inboxConfiguration.fullSyncState, 'failed'),
          and(
            notInArray(inboxConfiguration.fullSyncState, ['ready']),
            lt(
              sql`COALESCE(${inboxConfiguration.fullSyncHeartbeatAt}, '-infinity'::timestamptz)`,
              sql`NOW() - ${STUCK_FULL_SYNC_THRESHOLD_MINUTES} * INTERVAL '1 minute'`,
            ),
          ),
        ),
      );

    if (stuckConfigs.length === 0) {
      return;
    }

    this.logger.log({ msg: 'Found stuck full sync configurations', count: stuckConfigs.length });

    for (const config of stuckConfigs) {
      this.logger.log({
        msg: 'Publishing full sync recovery event',
        userProfileId: config.userProfileId,
      });
      const event = FullSyncEventDto.parse({
        type: 'unique.outlook-semantic-mcp.full-sync.recovery-requested',
        payload: { userProfileId: config.userProfileId },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    }
  }

  private async recoverStuckLiveCatchUps(): Promise<void> {
    const stuckConfigs = await this.db
      .select({ userProfileId: inboxConfiguration.userProfileId })
      .from(inboxConfiguration)
      .where(
        and(
          notInArray(inboxConfiguration.liveCatchUpState, ['ready']),
          lt(
            sql`COALESCE(${inboxConfiguration.liveCatchUpHeartbeatAt}, '-infinity'::timestamptz)`,
            sql`NOW() - ${STUCK_LIVE_CATCHUP_THRESHOLD_MINUTES} * INTERVAL '1 minute'`,
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
