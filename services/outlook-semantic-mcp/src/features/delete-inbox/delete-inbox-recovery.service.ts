import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { and, isNotNull, isNull, lt, or } from 'drizzle-orm';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { IngestionConfig, ingestionConfig, McpBackendType } from '~/config';
import { DRIZZLE, DrizzleDatabase, inboxConfigurations } from '~/db';
import { NewTrace } from '~/features/tracing.utils';
import { getThreshold } from '~/utils/get-threshold';
import { DeleteInboxDataEventDto } from './delete-inbox-data-event.dto';
import { STALE_DELETE_INBOX_CONFIGURATION_THRESHOLD_IN_MINUTES } from './execute-inbox-deletion.command';

@Injectable()
export class DeleteInboxRecoveryService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(ingestionConfig.KEY) private readonly config: IngestionConfig,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    if (this.config.mcpBackend !== 'MicrosoftGraphAndUniqueApi') {
      return;
    }
    this.logger.log({ msg: 'DeleteInboxRecoveryService is shutting down...' });
    this.isShuttingDown = true;
    try {
      const job = this.schedulerRegistry.getCronJob('delete-inbox-data-recovery');
      job.stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping delete-inbox-data-recovery cron job', err });
    }
  }

  private setupCronJob(): void {
    if (this.config.mcpBackend !== McpBackendType.MicrosoftGraphAndUniqueApi) {
      return;
    }
    const job = new CronJob(this.config.deleteInboxRecoveryCron, async () => {
      try {
        await this.checkAndRetriggerStuckDeletions();
      } catch (err) {
        this.logger.error({
          msg: 'An unexpected error occurred during delete inbox data recovery scan',
          err,
        });
      }
    });

    this.schedulerRegistry.addCronJob('delete-inbox-data-recovery', job);
    job.start();
  }

  @NewTrace('cron.delete-inbox-recovery')
  public async checkAndRetriggerStuckDeletions(): Promise<void> {
    if (this.isShuttingDown) {
      return;
    }

    this.logger.log({ msg: 'Delete inbox data recovery scan triggered' });

    const threshold = getThreshold(STALE_DELETE_INBOX_CONFIGURATION_THRESHOLD_IN_MINUTES);
    const configs = await this.db
      .select({ userProfileId: inboxConfigurations.userProfileId })
      .from(inboxConfigurations)
      .where(
        or(
          and(
            isNotNull(inboxConfigurations.deletingInboxStartedAt),
            lt(inboxConfigurations.deletingHeartbeatAt, threshold),
          ),
          and(
            isNotNull(inboxConfigurations.deletingInboxStartedAt),
            isNull(inboxConfigurations.deletingHeartbeatAt),
          ),
        ),
      );

    if (configs.length === 0) {
      return;
    }

    this.logger.log({
      msg: 'Publishing delete inbox data retrigger events',
      count: configs.length,
    });

    for (const { userProfileId } of configs) {
      const event = DeleteInboxDataEventDto.parse({
        type: 'unique.outlook-semantic-mcp.delete-inbox-data.execute',
        payload: { userProfileId },
      });
      await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
    }
  }
}
