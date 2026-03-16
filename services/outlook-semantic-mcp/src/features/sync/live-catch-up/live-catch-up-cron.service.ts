import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { gt, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/db';
import { LiveCatchUpEventDto } from './live-catch-up-event.dto';

const LIVE_CATCH_UP_CRON_SCHEDULE = '*/10 * * * *';

@Injectable()
export class LiveCatchUpCronService implements OnModuleInit, OnModuleDestroy {
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
    this.logger.log({ msg: 'LiveCatchUpCronService is shutting down...' });
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob('live-catch-up-cron');
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping live-catch-up-cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(LIVE_CATCH_UP_CRON_SCHEDULE, () => {
      void this.runLiveCatchUpForAllSubscriptions();
    });

    this.schedulerRegistry.addCronJob('live-catch-up-cron', job);
    job.start();
  }

  public async runLiveCatchUpForAllSubscriptions(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping live catch-up cron due to shutdown' });
      return;
    }

    try {
      this.logger.log({ msg: 'Live catch-up cron triggered' });

      const validSubscriptions = await this.db
        .select({ subscriptionId: subscriptions.subscriptionId })
        .from(subscriptions)
        .where(gt(subscriptions.expiresAt, sql`NOW()`));

      if (validSubscriptions.length === 0) {
        this.logger.log({ msg: 'No valid subscriptions found, skipping live catch-up cron' });
        return;
      }

      this.logger.log({ msg: 'Publishing live catch-up events', count: validSubscriptions.length });

      for (const { subscriptionId } of validSubscriptions) {
        const event = LiveCatchUpEventDto.parse({
          type: 'unique.outlook-semantic-mcp.live-catch-up.execute',
          payload: { subscriptionId, messageIds: [] },
        });
        await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
      }
    } catch (err) {
      this.logger.error({
        msg: 'An unexpected error occurred during live catch-up cron',
        err,
      });
    }
  }
}
