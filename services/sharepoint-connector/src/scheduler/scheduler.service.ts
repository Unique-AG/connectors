import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { Cron, SchedulerRegistry } from '@nestjs/schedule';
import { CRON_EVERY_15_MINUTES } from '../constants/defaults.constants';
import { SharepointSynchronizationService } from '../sharepoint-synchronization/sharepoint-synchronization.service';

@Injectable()
export class SchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly sharepointScanner: SharepointSynchronizationService,
    private readonly schedulerRegistry: SchedulerRegistry,
  ) {
    this.logger.log('SchedulerService initialized with distributed locking');
  }

  public onModuleInit() {
    this.logger.log('Triggering initial scan on service startup...');
    void this.runScheduledScan();
  }

  public onModuleDestroy() {
    this.logger.log('SchedulerService is shutting down...');
    this.isShuttingDown = true;
    this.destroyCronJobs();
  }

  @Cron(CRON_EVERY_15_MINUTES)
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
      this.logger.error(
        'An unexpected error occurred during the scheduled scan.',
        error instanceof Error ? error.stack : String(error),
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
      this.logger.error(
        'Error stopping cron jobs:',
        error instanceof Error ? error.stack : String(error),
      );
    }
  }
}
