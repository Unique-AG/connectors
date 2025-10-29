import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { Config } from '../config';
import { SharepointSynchronizationService } from '../sharepoint-synchronization/sharepoint-synchronization.service';
import { normalizeError } from '../utils/normalize-error';
@Injectable()
export class SchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly sharepointScanner: SharepointSynchronizationService,
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly configService: ConfigService<Config, true>,
  ) {}

  public onModuleInit() {
    this.logger.log('Triggering initial scan on service startup...');
    this.runScheduledScan();
    this.setupScheduledScan();
  }

  public onModuleDestroy() {
    this.logger.log('SchedulerService is shutting down...');
    this.isShuttingDown = true;
    this.destroyCronJobs();
  }

  private setupScheduledScan(): void {
    const cronExpression = this.configService.get('processing.scanIntervalCron', { infer: true });
    this.logger.log(`Scheduled scan configured with cron expression: ${cronExpression}`);

    const job = new CronJob(cronExpression, () => {
      this.runScheduledScan();
    });

    this.schedulerRegistry.addCronJob('sharepoint-scan', job);
    job.start();
  }

  public async runScheduledScan(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log('Skipping scheduled scan due to shutdown');
      return;
    }

    try {
      this.logger.log('Scheduler triggered');

      await this.sharepointScanner.synchronize();

      this.logger.log('SharePoint scan completed successfully.');
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error(
        `An unexpected error occurred during the scheduled scan: ${normalizedError.message}`,
      );
    }
  }

  private destroyCronJobs() {
    try {
      const jobs = this.schedulerRegistry.getCronJobs();
      jobs.forEach((job, jobName) => {
        this.logger.log(`Stopping cron job: ${jobName}`);
        job.stop();
      });
    } catch (error) {
      const normalizedError = normalizeError(error);
      this.logger.error(`Error stopping cron jobs: ${normalizedError.message}`);
    }
  }
}
