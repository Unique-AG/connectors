import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DelegatedAccessConfig, delegatedAccessConfig } from '~/config';
import { CacheData } from '~/db/schema/cache/cache.data';
import { NewTrace } from '~/features/tracing.utils';
import { PersistentCacheService } from '../persistent-cache/persistent-cache.service';
import {
  DISCOVER_DELEGATED_ACCESS_CACHE_KEY,
  DISCOVER_DELEGATED_ACCESS_NO_PROGRESS_THRESHOLD_MINUTES,
} from './discovery/discover-delegated-access.command';
import { DiscoverDelegatedAccessEventDto } from './discovery/discover-delegated-access-event.dto';
import { SyncDelegatedAccessEventDto } from './verification/sync-delegated-access-event';
import {
  SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_CACHE_KEY,
  SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_NO_PROGRESS_THRESHOLD_MINUTES,
} from './verification/sync-delegated-access-for-all-users.command';

@Injectable()
export class DelegatedAccessRecoverySchedulerService implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(this.constructor.name);
  private isShuttingDown = false;

  public constructor(
    private readonly schedulerRegistry: SchedulerRegistry,
    private readonly amqp: AmqpConnection,
    @Inject(delegatedAccessConfig.KEY) private readonly config: DelegatedAccessConfig,
    private readonly persistentCacheService: PersistentCacheService,
  ) {}

  public onModuleInit() {
    this.setupCronJob();
  }

  public onModuleDestroy() {
    if (this.config.scan === 'disabled') {
      return;
    }
    this.logger.log({ msg: 'DelegatedAccessRecoverySchedulerService is shutting down...' });
    this.isShuttingDown = true;
    try {
      this.schedulerRegistry.getCronJob('delegated-access-recovery').stop();
    } catch (err) {
      this.logger.error({ msg: 'Error stopping delegated-access-recovery cron job', err });
    }
  }

  private setupCronJob(): void {
    if (this.config.scan === 'disabled') {
      return;
    }

    const job = new CronJob(this.config.recoveryCronSchedule, async () => {
      try {
        await this.runRecovery();
      } catch (err) {
        this.logger.error({
          msg: 'An unexpected error occurred during delegated access recovery scan',
          err,
        });
      }
    });

    this.schedulerRegistry.addCronJob('delegated-access-recovery', job);
    job.start();
  }

  @NewTrace('cron.delegated-access-recovery')
  public async runRecovery(): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping delegated access recovery scan due to shutdown' });
      return;
    }

    await this.recoverDiscovery();

    if (this.config.scan === 'granularAccess') {
      await this.recoverVerification();
    }
  }

  private async recoverDiscovery(): Promise<void> {
    const cached = await this.persistentCacheService.get(DISCOVER_DELEGATED_ACCESS_CACHE_KEY);
    if (!this.isStuck(cached, DISCOVER_DELEGATED_ACCESS_NO_PROGRESS_THRESHOLD_MINUTES)) {
      return;
    }

    this.logger.warn({
      msg: 'Detected stuck delegated access discovery, triggering recovery',
      state: cached?.dataType === 'DelegatedAccessDiscovery' ? cached.payload.state : undefined,
    });

    const event = DiscoverDelegatedAccessEventDto.parse({
      type: 'unique.outlook-semantic-mcp.delegated-access.discover',
      payload: {},
    });
    await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
  }

  private async recoverVerification(): Promise<void> {
    const cached = await this.persistentCacheService.get(
      SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_CACHE_KEY,
    );
    if (!this.isStuck(cached, SYNC_DELEGATED_ACCESS_FOR_ALL_USERS_NO_PROGRESS_THRESHOLD_MINUTES)) {
      return;
    }

    this.logger.warn({
      msg: 'Detected stuck delegated access verification, triggering recovery',
      state: cached?.dataType === 'DelegatedAccessVerification' ? cached.payload.state : undefined,
    });

    const event = SyncDelegatedAccessEventDto.parse({
      type: 'unique.outlook-semantic-mcp.delegated-access.sync',
      payload: {},
    });
    await this.amqp.publish(MAIN_EXCHANGE.name, event.type, event);
  }

  private isStuck(cached: CacheData | null, thresholdMinutes: number): boolean {
    if (!cached) {
      return false;
    }
    if (cached.payload.state === 'failed') {
      return true;
    }
    if (cached.payload.state === 'running') {
      return Date.now() - cached.payload.lastProgressRegisteredAt >= thresholdMinutes * 60 * 1000;
    }
    return false;
  }
}
