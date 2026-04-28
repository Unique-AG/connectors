import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { gt, sql } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { AppConfig, appConfig } from '~/config';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/db';
import { DiscoverDelegatedAccessEventDto } from './discover-delegated-access-event.dto';

@Injectable()
export class DiscoverDelegatedAccessSchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    this.logger.log({ msg: 'DiscoverDelegatedAccessSchedulerService is shutting down...' });
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob('delegated-access-discovery');
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping delegated-access-discovery cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(this.config.delegatedAccessDiscoveryCronSchedule, async () => {
      try {
        await this.triggerDiscoveryForConnectedUsers();
      } catch (err) {
        this.logger.error({
          msg: 'An unexpected error occurred during delegated access discovery scan',
          err,
        });
      }
    });

    this.schedulerRegistry.addCronJob('delegated-access-discovery', job);
    job.start();
  }

  public async triggerDiscoveryForConnectedUsers(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping delegated access discovery scan due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'Delegated access discovery scan triggered' });

    const users = await this.db
      .select({ userProfileId: subscriptions.userProfileId })
      .from(subscriptions)
      .where(gt(subscriptions.expiresAt, sql`NOW()`));

    if (users.length === 0) {
      return;
    }

    this.logger.log({
      msg: 'Publishing delegated access discovery events',
      count: users.length,
    });

    for (const { userProfileId } of users) {
      const event = DiscoverDelegatedAccessEventDto.parse({
        type: 'unique.outlook-semantic-mcp.delegated-access.discover',
        payload: { delegateUserId: userProfileId },
      });
      await this.amqp.publish(
        MAIN_EXCHANGE.name,
        `unique.outlook-semantic-mcp.delegated-access.discover.${userProfileId}`,
        event,
      );
    }
  }
}
