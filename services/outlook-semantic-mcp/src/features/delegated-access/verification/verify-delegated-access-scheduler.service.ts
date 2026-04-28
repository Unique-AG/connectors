import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, DrizzleDatabase, delegatedAccessPipeline } from '~/db';
import { VerifyDelegatedAccessEventDto } from './verify-delegated-access-event.dto';

const VERIFICATION_CRON_SCHEDULE = '0 */4 * * *';

@Injectable()
export class VerifyDelegatedAccessSchedulerService implements OnModuleInit, OnModuleDestroy {
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
    this.logger.log({ msg: 'VerifyDelegatedAccessSchedulerService is shutting down...' });
    this.isShuttingDown = true;
    try {
      this.schedulerRegistry.getCronJob('delegated-access-verification').stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping cron job', err });
    }
  }

  private setupCronJob(): void {
    const job = new CronJob(VERIFICATION_CRON_SCHEDULE, async () => {
      try {
        await this.triggerVerificationForPipelineRows();
      } catch (err) {
        this.logger.error({
          msg: 'An unexpected error occurred during delegated access verification scan',
          err,
        });
      }
    });

    this.schedulerRegistry.addCronJob('delegated-access-verification', job);
    job.start();
  }

  public async triggerVerificationForPipelineRows(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping verification scan due to shutdown' });
      return;
    }

    this.logger.log({ msg: 'Delegated access verification scan triggered' });

    const rows = await this.db.select({ id: delegatedAccessPipeline.id }).from(delegatedAccessPipeline);

    for (const { id } of rows) {
      const event = VerifyDelegatedAccessEventDto.parse({
        type: 'unique.outlook-semantic-mcp.delegated-access.verify',
        payload: { pipelineId: id },
      });
      await this.amqp.publish(
        MAIN_EXCHANGE.name,
        `unique.outlook-semantic-mcp.delegated-access.verify.${id}`,
        event,
      );
    }
  }
}
