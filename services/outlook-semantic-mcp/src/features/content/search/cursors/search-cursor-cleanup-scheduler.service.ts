import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { NewTrace } from '~/features/tracing.utils';
import { SEARCH_CONFIG } from '../search.config';
import { SearchCursorRepository } from './search-cursor.repository';

const CRON_JOB_NAME = 'search-cursor-cleanup';
const DAILY_AT_3AM = '0 3 * * *';
const DAY_MS = 24 * 60 * 60 * 1000;

@Injectable()
export class SearchCursorCleanupSchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly searchCursorRepository: SearchCursorRepository,
  ) {}

  public onModuleInit() {
    const job = new CronJob(DAILY_AT_3AM, () => {
      void this.runCleanup();
    });
    this.schedulerRegistry.addCronJob(CRON_JOB_NAME, job);
    job.start();
  }

  public onModuleDestroy() {
    this.isShuttingDown = true;
    try {
      this.schedulerRegistry.getCronJob(CRON_JOB_NAME).stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping search cursor cleanup cron job', err });
    }
  }

  @NewTrace('cron.search-cursor-cleanup')
  public async runCleanup(): Promise<void> {
    if (this.isShuttingDown) {
      return;
    }
    try {
      const cutoff = new Date(Date.now() - SEARCH_CONFIG.cursorRetentionDays * DAY_MS);
      const deleted = await this.searchCursorRepository.deleteCreatedBefore(cutoff);
      this.logger.log({ msg: 'Deleted expired search cursors', deleted });
    } catch (err) {
      this.logger.error({ msg: 'An unexpected error occurred during search cursor cleanup', err });
    }
  }
}
