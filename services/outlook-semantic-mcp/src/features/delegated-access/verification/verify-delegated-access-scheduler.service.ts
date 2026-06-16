import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { NewTrace } from '~/features/tracing.utils';
import { SyncDelegatedAccessEventDto } from './sync-delegated-access-event';

@Injectable()
export class VerifyDelegatedAccessSchedulerService implements OnModuleInit, OnModuleDestroy {
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
    if (this.config.scan === 'disabled' || this.config.scan === 'full_access_only') {
      return;
    }
    this.logger.log({ msg: 'VerifyDelegatedAccessSchedulerService is shutting down...' });
    this.isShuttingDown = true;
    try {
      this.schedulerRegistry.getCronJob('delegated-access-sync').stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping cron job', err });
    }
  }

  private setupCronJob(): void {
    if (this.config.scan === 'disabled' || this.config.scan === 'full_access_only') {
      return;
    }
    const job = new CronJob(this.config.verificationCronSchedule, async () => {
      try {
        await this.triggerVerificationForAccounts();
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

  @NewTrace('cron.verify-delegated-access')
  public async triggerVerificationForAccounts(): Promise<void> {
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
