import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config/delegated-access.config';
import { NewTrace } from '~/features/tracing.utils';
import { DiscoverDelegatedAccessEventDto } from './discover-delegated-access-event.dto';

@Injectable()
export class DiscoverDelegatedAccessSchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    if (this.config.scan === 'disabled') {
      return;
    }
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
    if (this.config.scan === 'disabled') {
      return;
    }
    const job = new CronJob(this.config.discoveryCronSchedule, async () => {
      try {
        await this.triggerDiscovery();
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

  @NewTrace('cron.discover-delegated-access')
  public async triggerDiscovery(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping delegated access discovery scan due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'Delegated access discovery scan triggered' });

    const event = DiscoverDelegatedAccessEventDto.parse({
      type: 'unique.outlook-semantic-mcp.delegated-access.discover',
      payload: {},
    });
    await this.amqp.publish(
      MAIN_EXCHANGE.name,
      'unique.outlook-semantic-mcp.delegated-access.discover',
      event,
    );
  }
}
