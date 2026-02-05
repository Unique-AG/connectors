import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { Span, TraceService } from 'nestjs-otel';
import type { EmailSyncConfigNamespaced } from '~/config';
import { EmailSyncService } from './email-sync.service';

@Injectable()
export class EmailSyncScheduler implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(EmailSyncScheduler.name);
  private isShuttingDown = false;
  private isProcessing = false;

  public constructor(
    private readonly emailSyncService: EmailSyncService,
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly configService: ConfigService<EmailSyncConfigNamespaced, true>,
    private readonly trace: TraceService,
  ) {}

  public onModuleInit(): void {
    const enabled = this.configService.get('emailSync.enabled', { infer: true });
    if (!enabled) {
      this.logger.log('Email sync scheduler is disabled');
      return;
    }

    this.logger.log('Initializing email sync scheduler');
    this.setupScheduledSync();
  }

  public onModuleDestroy(): void {
    this.logger.log('EmailSyncScheduler is shutting down');
    this.isShuttingDown = true;
    this.destroyCronJobs();
  }

  private setupScheduledSync(): void {
    const cronExpression = this.configService.get('emailSync.syncIntervalCron', { infer: true });
    this.logger.log(`Email sync scheduled with cron expression: ${cronExpression}`);

    const job = new CronJob(cronExpression, () => {
      void this.runScheduledSync();
    });

    this.schedulerRegistry.addCronJob('email-sync', job);
    job.start();
  }

  @Span()
  public async runScheduledSync(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log('Skipping scheduled sync due to shutdown');
      return;
    }

    if (this.isProcessing) {
      this.logger.log('Skipping scheduled sync - previous sync still in progress');
      return;
    }

    const span = this.trace.getSpan();
    this.isProcessing = true;

    try {
      this.logger.log('Starting scheduled email sync');
      span?.addEvent('sync_started');

      const activeConfigs = await this.emailSyncService.getActiveConfigs();
      span?.setAttribute('active_config_count', activeConfigs.length);

      this.logger.debug(
        { configCount: activeConfigs.length },
        'Found active email sync configurations',
      );

      for (const config of activeConfigs) {
        if (this.isShuttingDown) {
          this.logger.log('Stopping sync processing due to shutdown');
          break;
        }

        try {
          span?.addEvent('processing_config', { configId: config.id });
          this.logger.debug({ configId: config.id }, 'Processing email sync configuration');

          // TODO: Do this in pharalel
          await this.emailSyncService.processDeltaSync(config);

          this.logger.log({ configId: config.id }, 'Email sync completed for configuration');
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : 'Unknown error';
          this.logger.error(
            { configId: config.id, error: errorMessage },
            'Failed to process email sync for configuration',
          );
          span?.addEvent('config_error', { configId: config.id, error: errorMessage });
        }
      }

      span?.addEvent('sync_completed');
      this.logger.log('Scheduled email sync completed');
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      this.logger.error({ error: errorMessage }, 'Unexpected error during scheduled sync');
      span?.setAttribute('error', true);
      span?.setAttribute('error_message', errorMessage);
    } finally {
      this.isProcessing = false;
    }
  }

  private destroyCronJobs(): void {
    try {
      const jobs = this.schedulerRegistry.getCronJobs();
      jobs.forEach((job, jobName) => {
        if (jobName === 'email-sync') {
          this.logger.log(`Stopping cron job: ${jobName}`);
          job.stop();
        }
      });
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : 'Unknown error';
      this.logger.error({ error: errorMessage }, 'Error stopping cron jobs');
    }
  }
}
