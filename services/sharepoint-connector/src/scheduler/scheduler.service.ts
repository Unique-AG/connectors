import { Injectable, Logger } from '@nestjs/common';
import { Cron } from '@nestjs/schedule';
import { CRON_EVERY_15_MINUTES } from '../constants/defaults.constants';
import { SharepointScannerService } from '../sharepoint-scanner/sharepoint-scanner.service';

@Injectable()
export class SchedulerService {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(private readonly sharepointScanner: SharepointScannerService) {
    this.logger.log('SchedulerService initialized with distributed locking');
  }

  public onModuleInit() {
    this.logger.log('Triggering initial scan on service startup...');
    void this.runScheduledScan();
  }

  @Cron(CRON_EVERY_15_MINUTES)
  public async runScheduledScan(): Promise<void> {
    this.logger.log('Scheduler triggered');
    try {
      await this.sharepointScanner.scanForWork();
      this.logger.log('SharePoint scan completed successfully.');
    } catch (error) {
      this.logger.error(
        'An unexpected error occurred during the scheduled scan.',
        error instanceof Error ? error.stack : String(error),
      );
    }
  }
}
