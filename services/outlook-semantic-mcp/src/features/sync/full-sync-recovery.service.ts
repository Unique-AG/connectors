import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, gt, isNull, lt, or, SQL, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration, subscriptions } from '~/db';
import { FullSyncEventDto } from './full-sync/full-sync-event.dto';

const FULL_SYNC_RECOVERY_CRON_SCHEDULE = '*/2 * * * *';
const STALE_HEARTBEAT_MINUTES = 20;

@Injectable()
export class FullSyncRecoveryService implements OnModuleInit, OnModuleDestroy {
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
    this.logger.log({ msg: 'FullSyncRecoveryService is shutting down...' });
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob('full-sync-recovery');
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping full-sync-recovery cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(FULL_SYNC_RECOVERY_CRON_SCHEDULE, () => {
      void this.publishRetriggerEvents();
    });

    this.schedulerRegistry.addCronJob('full-sync-recovery', job);
    job.start();
  }

  public async publishRetriggerEvents(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping full sync recovery scan due to shutdown' });
      return;
    }

    try {
      this.logger.log({ msg: 'Full sync recovery scan triggered' });

      const staleThreshold = getThreshold(STALE_HEARTBEAT_MINUTES);
      const waitingForIngestionThreshold = getThreshold(5);

      const configs = await this.db
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
            and(
              eq(inboxConfiguration.fullSyncState, 'waiting-for-ingestion'),
              or(
                isNull(inboxConfiguration.fullSyncHeartbeatAt),
                lt(inboxConfiguration.fullSyncHeartbeatAt, waitingForIngestionThreshold),
              ),
            ),
            eq(inboxConfiguration.fullSyncState, 'failed'),
            and(
              eq(inboxConfiguration.fullSyncState, 'running'),
              or(
                isNull(inboxConfiguration.fullSyncHeartbeatAt),
                lt(inboxConfiguration.fullSyncHeartbeatAt, staleThreshold),
              ),
            ),
          ),
        );

      if (configs.length === 0) {
        return;
      }

      this.logger.log({
        msg: 'Publishing full sync retrigger events',
        count: configs.length,
      });

      for (const { userProfileId } of configs) {
        const event = FullSyncEventDto.parse({
          type: 'unique.outlook-semantic-mcp.full-sync.retrigger',
          payload: { userProfileId },
        });
        await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
      }
    } catch (err) {
      this.logger.error({
        msg: 'An unexpected error occurred during full sync recovery scan',
        err,
      });
    }
  }
}

const getThreshold = (thresholdInMinutes: number): SQL<unknown> => {
  return sql`NOW() - (${thresholdInMinutes} * INTERVAL '1 minute')`;
};
