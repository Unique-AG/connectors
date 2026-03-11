import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { and, lt, notInArray, sql } from 'drizzle-orm';
import { CronJob } from 'cron';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfiguration } from '~/db';
import { FullSyncRecoveryEventDto } from './dtos/full-sync-recovery-event.dto';

const STUCK_SYNC_THRESHOLD_MINUTES = 15;
const RECOVERY_CRON_SCHEDULE = '* * * * *';

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

      const stuckConfigs = await this.db
        .select({ userProfileId: inboxConfiguration.userProfileId })
        .from(inboxConfiguration)
        .where(
          and(
            notInArray(inboxConfiguration.fullSyncState, ['full-sync-finished', 'failed']),
            lt(
              sql`GREATEST(COALESCE(${inboxConfiguration.lastFullSyncStartedAt}, '-infinity'::timestamptz), ${inboxConfiguration.updatedAt})`,
              sql`NOW() - ${STUCK_SYNC_THRESHOLD_MINUTES} * INTERVAL '1 minute'`,
            ),
          ),
        );

      if (stuckConfigs.length === 0) {
        return;
      }

      this.logger.log({ msg: 'Found stuck inbox configurations', count: stuckConfigs.length });

      for (const config of stuckConfigs) {
        this.logger.log({ msg: 'Publishing recovery event', userProfileId: config.userProfileId });
        const event = FullSyncRecoveryEventDto.parse({
          type: 'unique.outlook-semantic-mcp.full-sync.recovery-requested',
          payload: { userProfileId: config.userProfileId },
        });
        await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
      }
    } catch (err) {
      this.logger.error({ msg: 'An unexpected error occurred during stuck sync recovery scan', err });
    }
  }
}
