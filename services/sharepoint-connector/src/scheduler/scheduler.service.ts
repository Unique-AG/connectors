import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { Config } from '../config';
import { FullSyncStep } from '../constants/sync-step.enum';
import { SyncStatusStore } from '../health/sync-status.store';
import { SharepointSynchronizationService } from '../sharepoint-synchronization/sharepoint-synchronization.service';
import { sanitizeError } from '../utils/normalize-error';

@Injectable()
export class SchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly sharepointScanner: SharepointSynchronizationService,
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly configService: ConfigService<Config, true>,
    private readonly syncStatusStore: SyncStatusStore,
  ) {}

  public onModuleInit() {
    this.logger.log('Triggering initial scan on service startup...');
    void this.runScheduledScan();
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
      void this.runScheduledScan();
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

      const { fullResult, siteResults } = await this.sharepointScanner.synchronize();

      if (fullResult.status !== 'skipped' || fullResult.reason !== 'scan_in_progress') {
        this.syncStatusStore.record({
          timestamp: new Date(),
          fullResult,
          siteResults,
        });
        this.logger.log('SharePoint scan ended');
      }
    } catch (error) {
      // siteResults is empty because an unexpected throw from synchronize() means the run
      // crashed before it could produce any per-site results.
      this.syncStatusStore.record({
        timestamp: new Date(),
        fullResult: { status: 'failure', step: FullSyncStep.Unknown },
        siteResults: [],
      });
      this.logger.error({
        msg: 'An unexpected error occurred during the scheduled scan',
        error: sanitizeError(error),
      });
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
      this.logger.error({
        msg: 'Error stopping cron jobs',
        error: sanitizeError(error),
      });
    }
  }
}
