import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, gt, lt, or, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations, subscriptions } from '~/db';
import { traceEvent } from '~/features/tracing.utils';
import { getThreshold } from '~/utils/get-threshold';
import {
  FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES,
  READY_LIVE_CATCHUP_THRESHOLD_MINUTES,
  RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES,
} from './live-catch-up/live-catch-up.command';
import { LiveCatchUpEventDto } from './live-catch-up/live-catch-up-event.dto';

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
      this.logger.error({
        msg: 'Error stopping live-catchup-recovery cron job',
        err,
      });
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
      this.logger.log({
        msg: 'Skipping live catchup recovery scan due to shutdown',
      });
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
      .select({
        userProfileId: inboxConfigurations.userProfileId,
        subscriptionId: subscriptions.subscriptionId,
        liveCatchUpState: inboxConfigurations.liveCatchUpState,
      })
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
            // Normally we should not do anything about the ready state since we get webhook notifications
            // but because microsoft does not trigger this webhook if a user updates the categories to be
            // on the safe side we trigger every 4 hours if the user did not receive any emails
            eq(inboxConfigurations.liveCatchUpState, 'ready'),
            lt(
              inboxConfigurations.liveCatchUpHeartbeatAt,
              getThreshold(READY_LIVE_CATCHUP_THRESHOLD_MINUTES),
            ),
          ),
          and(
            eq(inboxConfigurations.liveCatchUpState, 'failed'),
            lt(
              inboxConfigurations.liveCatchUpHeartbeatAt,
              getThreshold(FAILED_LIVE_CATCHUP_THRESHOLD_MINUTES),
            ),
          ),
          and(
            eq(inboxConfigurations.liveCatchUpState, 'running'),
            lt(
              inboxConfigurations.liveCatchUpHeartbeatAt,
              getThreshold(RUNNING_LIVE_CATCHUP_THRESHOLD_MINUTES),
            ),
          ),
        ),
      );

    if (stuckConfigs.length === 0) {
      return;
    }

    await this.rerunLiveCatchups(stuckConfigs);
  }

  private async rerunLiveCatchups(readyLiveCatchups: { subscriptionId: string }[]): Promise<void> {
    if (!readyLiveCatchups.length) {
      this.logger.log({
        msg: 'No live catch-ups which did not run for a long time',
      });
      return;
    }

    traceEvent('live-catch-up stuck recovery triggered', {
      count: readyLiveCatchups.length,
      subscriptionIds: readyLiveCatchups.map((c) => c.subscriptionId),
    });

    this.logger.log({
      msg: 'Found ready live catch-up configurations',
      count: readyLiveCatchups.length,
    });

    for (const { subscriptionId } of readyLiveCatchups) {
      this.logger.log({
        msg: 'Publishing live catch-up recovery event',
        subscriptionId,
      });
      const event = LiveCatchUpEventDto.parse({
        type: 'unique.outlook-semantic-mcp.live-catch-up.execute',
        payload: { subscriptionId, messageIds: [] },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    }
  }
}
