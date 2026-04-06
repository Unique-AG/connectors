import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, eq, gt, lt, or, sql } from 'drizzle-orm';
import z from 'zod';
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
export class LiveCatchupSchedulerService implements OnModuleInit, OnModuleDestroy {
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
    this.logger.log({ msg: 'LiveCatchupSchedulerService is shutting down...' });
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
      this.runRecoveryScan();
      this.runReadyLiveCatchupsWhichDidNotRunRecently();
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

  public async runReadyLiveCatchupsWhichDidNotRunRecently(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({
        msg: 'Skipping live catchup recovery scan due to shutdown',
      });
      return;
    }

    try {
      this.logger.log({ msg: 'Live catchup recovery scan triggered' });
      await this.rerunReadyLiveCatchupsWhichDidNotRunRecently();
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

    await this.rerunLiveCatchups(
      stuckConfigs.map(({ subscriptionId }) =>
        LiveCatchUpEventDto.parse({
          type: 'unique.outlook-semantic-mcp.live-catch-up.execute',
          payload: { subscriptionId },
        }),
      ),
    );
  }

  private async rerunReadyLiveCatchupsWhichDidNotRunRecently(): Promise<void> {
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
            eq(inboxConfigurations.liveCatchUpState, 'ready'),
            lt(
              inboxConfigurations.liveCatchUpHeartbeatAt,
              getThreshold(READY_LIVE_CATCHUP_THRESHOLD_MINUTES),
            ),
          ),
        ),
      );

    if (stuckConfigs.length === 0) {
      return;
    }

    await this.rerunLiveCatchups(
      stuckConfigs.map(({ subscriptionId }) =>
        LiveCatchUpEventDto.parse({
          type: 'unique.outlook-semantic-mcp.live-catch-up.ready-recheck',
          payload: { subscriptionId },
        }),
      ),
    );
  }

  private async rerunLiveCatchups(events: z.infer<typeof LiveCatchUpEventDto>[]): Promise<void> {
    if (!events.length) {
      this.logger.log({
        msg: 'No live catch-ups which did not run for a long time',
      });
      return;
    }

    traceEvent('live-catch-up stuck recovery triggered', {
      count: events.length,
      subscriptionIds: events.map((subscription) => subscription.payload.subscriptionId),
    });

    this.logger.log({
      msg: 'Found ready live catch-up configurations',
      count: events.length,
    });

    for (const event of events) {
      this.logger.log({
        msg: `Publishing live catch-up: ${event.type}`,
        subscriptionId: event.payload.subscriptionId,
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    }
  }
}
