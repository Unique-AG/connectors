import type { IUptimeCheck } from '@unique-ag/up';
import { UptimeCheck } from '@unique-ag/up';
import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { Config } from '../config';
import { SyncStep } from '../constants/sync-step.enum';
import {
  type FullSyncResult,
  SharepointSynchronizationService,
} from '../sharepoint-synchronization/sharepoint-synchronization.service';
import { sanitizeError } from '../utils/normalize-error';

@Injectable()
@UptimeCheck('scheduler')
export class SchedulerService implements OnModuleInit, OnModuleDestroy, IUptimeCheck {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;
  private lastRunResult: FullSyncResult | null = null;
  private lastRunTimestamp: Date | null = null;

  public constructor(
    private readonly sharepointScanner: SharepointSynchronizationService,
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly configService: ConfigService<Config, true>,
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

      const result = await this.sharepointScanner.synchronize();

      this.lastRunResult = result;
      this.lastRunTimestamp = new Date();

      if (result.status !== 'skipped' || result.reason !== 'scan_in_progress') {
        this.logger.log('SharePoint scan ended');
      }
    } catch (error) {
      this.lastRunResult = { status: 'failure', step: SyncStep.Unknown };
      this.lastRunTimestamp = new Date();

      this.logger.error({
        msg: 'An unexpected error occurred during the scheduled scan',
        error: sanitizeError(error),
      });
    }
  }

  public async checkUp(): Promise<{ status: 'up' | 'down'; message?: string }> {
    if (this.lastRunResult === null) {
      return { status: 'down', message: 'No scan has completed yet' };
    }

    const lastRunAt = this.lastRunTimestamp?.toISOString();

    if (this.lastRunResult.status === 'success') {
      return { status: 'up', message: lastRunAt };
    }

    if (this.lastRunResult.status === 'skipped') {
      return { status: 'up', message: `${this.lastRunResult.reason} (${lastRunAt})` };
    }

    return {
      status: 'down',
      message: `Last scan failed at step: ${this.lastRunResult.step} (${lastRunAt})`,
    };
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
