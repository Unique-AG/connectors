import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { SyncDirectoriesForSubscriptionsCommand } from './sync-directories-for-subscriptions.command';

@Injectable()
export class DirectorySyncSchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private syncDirectoriesForSubscriptionsCommand: SyncDirectoriesForSubscriptionsCommand,
  ) {}

  public onModuleInit() {
    this.logger.log('Triggering initial scan on service startup...');
    // void this.runScheduledScan();
    this.setupScheduledScan();
  }

  public onModuleDestroy() {
    this.logger.log('SchedulerService is shutting down...');
    this.isShuttingDown = true;
    this.destroyCronJobs();
  }

  private setupScheduledScan(): void {
    const job = new CronJob(`*/5 * * * *`, () => {
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

      await this.syncDirectoriesForSubscriptionsCommand.run();
    } catch (err) {
      this.logger.error({ msg: 'An unexpected error occurred during the scheduled scan', err });
    }
  }

  private destroyCronJobs() {
    try {
      const jobs = this.schedulerRegistry.getCronJobs();
      jobs.forEach((job, jobName) => {
        this.logger.log(`Stopping cron job: ${jobName}`);
        job.stop();
      });
    } catch (err) {
      this.logger.error({ msg: 'Error stopping cron jobs', err });
    }
  }
}
