import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, gt, lt, or, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions } from '~/db';
import { getThreshold } from '~/utils/get-threshold';
import {
  FAILED_HEARTBEAT_MINUTES,
  RUNNING_HEARTBEAT_MINUTES,
  WAITING_FOR_INGESTION_HEARTBEAT_MINUTES,
} from './full-sync/full-sync.command';
import { FullSyncEventDto } from './full-sync/full-sync-event.dto';

const FULL_SYNC_RECOVERY_CRON_SCHEDULE = '*/2 * * * *';

@Injectable()
export class FullSyncSchedulerService implements OnModuleInit, OnModuleDestroy {
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
    const job = new CronJob(FULL_SYNC_RECOVERY_CRON_SCHEDULE, async () => {
      try {
        await this.checkAndRetriggerStuckFullSyncs();
      } catch (err) {
        this.logger.error({
          msg: 'An unexpected error occurred during full sync recovery scan',
          err,
        });
      }
    });

    this.schedulerRegistry.addCronJob('full-sync-recovery', job);
    job.start();
  }

  public async checkAndRetriggerStuckFullSyncs(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping full sync recovery scan due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'Full sync recovery scan triggered' });

    const runningThreshold = getThreshold(RUNNING_HEARTBEAT_MINUTES);
    const waitingForIngestionThreshold = getThreshold(WAITING_FOR_INGESTION_HEARTBEAT_MINUTES);
    const waitingForFailedThreshold = getThreshold(FAILED_HEARTBEAT_MINUTES);

    const configs = await this.db
      .select({ userProfileId: inboxConfigurations.userProfileId })
      .from(inboxConfigurations)
      .innerJoin(
        subscriptions,
        and(
          eq(subscriptions.userProfileId, inboxConfigurations.userProfileId),
          gt(subscriptions.expiresAt, sql`NOW()`),
        ),
      )
      .where(
        or(
          and(
            eq(inboxConfigurations.fullSyncState, 'waiting-for-ingestion'),
            lt(inboxConfigurations.fullSyncHeartbeatAt, waitingForIngestionThreshold),
          ),
          and(
            eq(inboxConfigurations.fullSyncState, 'failed'),
            lt(inboxConfigurations.fullSyncHeartbeatAt, waitingForFailedThreshold),
          ),
          and(
            eq(inboxConfigurations.fullSyncState, 'running'),
            lt(inboxConfigurations.fullSyncHeartbeatAt, runningThreshold),
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
  }
}
