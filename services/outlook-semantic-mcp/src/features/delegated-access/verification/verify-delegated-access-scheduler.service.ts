import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { AppConfig, appConfig } from '~/config';
import { SyncDelegatedAccessEventDto } from './sync-delegated-access-event';

@Injectable()
export class VerifyDelegatedAccessSchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(appConfig.KEY) private readonly config: AppConfig,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    this.logger.log({ msg: 'VerifyDelegatedAccessSchedulerService is shutting down...' });
    this.isShuttingDown = true;
    try {
      this.schedulerRegistry.getCronJob('delegated-access-sync').stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(this.config.delegatedAccessVerificationCronSchedule, async () => {
      try {
        await this.triggerVerificationForPipelineRows();
      } catch (err) {
        this.logger.error({
          msg: 'An unexpected error occurred during delegated access verification scan',
          err,
        });
      }
    });

    this.schedulerRegistry.addCronJob('delegated-access-sync', job);
    job.start();
  }

  public async triggerVerificationForPipelineRows(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping verification scan due to shutdown' });
      return;
    }

    const event = SyncDelegatedAccessEventDto.parse({
      type: 'unique.outlook-semantic-mcp.delegated-access.sync',
      payload: {},
    });
    await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    this.logger.log({ msg: 'Delegated access sync triggered' });
  }
}
