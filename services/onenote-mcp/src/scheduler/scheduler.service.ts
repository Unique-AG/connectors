import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { CronJob } from 'cron';
import pLimit from 'p-limit';
import type { SyncConfigNamespaced } from '~/config';
import { OneNoteSyncService } from '~/onenote/onenote-sync.service';
import { normalizeError } from '~/utils/normalize-error';

@Injectable()
export class SchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(SchedulerService.name);
  private cronJob: CronJob | null = null;
  private isSyncRunning = false;

  public constructor(
    private readonly config: ConfigService<SyncConfigNamespaced, true>,
    private readonly syncService: OneNoteSyncService,
  ) {}

  public onModuleInit(): void {
    const cronExpression = this.config.get('sync.intervalCron', { infer: true });

    this.logger.log({ cronExpression }, 'Initializing OneNote sync scheduler');

    this.cronJob = CronJob.from({
      cronTime: cronExpression,
      onTick: () => void this.runScheduledSync(),
      start: true,
    });

    void this.runScheduledSync();
  }

  public onModuleDestroy(): void {
    this.cronJob?.stop();
    this.cronJob = null;
    this.logger.log('Stopped OneNote sync scheduler');
  }

  private async runScheduledSync(): Promise<void> {
    if (this.isSyncRunning) {
      this.logger.debug('Skipping sync tick: previous sync still in progress');
      return;
    }

    this.isSyncRunning = true;
    const startTime = Date.now();

    try {
      const userProfileIds = await this.syncService.getAllUserProfileIds();
      if (userProfileIds.length === 0) {
        this.logger.debug('No user profiles found, skipping sync');
        return;
      }

      const concurrency = this.config.get('sync.concurrency', { infer: true });
      const limit = pLimit(concurrency);

      this.logger.log(
        { userCount: userProfileIds.length, concurrency },
        'Starting scheduled OneNote sync',
      );

      await Promise.allSettled(
        userProfileIds.map((id) =>
          limit(async () => {
            try {
              await this.syncService.syncUser(id);
            } catch (error) {
              const normalized = normalizeError(error);
              this.logger.error(
                {
                  userProfileId: id,
                  errorMessage: normalized.message,
                  errorStack: normalized.stack,
                  errorName: normalized.name,
                },
                'Sync failed for user',
              );
            }
          }),
        ),
      );

      const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
      this.logger.log(
        { userCount: userProfileIds.length, elapsedSeconds: elapsed },
        'Completed scheduled OneNote sync',
      );
    } catch (error) {
      const normalized = normalizeError(error);
      this.logger.error(
        {
          errorMessage: normalized.message,
          errorStack: normalized.stack,
          errorName: normalized.name,
        },
        'Scheduled sync encountered an error',
      );
    } finally {
      this.isSyncRunning = false;
    }
  }
}
