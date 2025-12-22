import { Injectable, Logger, OnModuleDestroy, OnModuleInit } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { Config } from '../config';
import { TenantConfigLoaderService } from '../config/tenant-config-loader.service';
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
    private readonly tenantConfigLoaderService: TenantConfigLoaderService,
  ) {}

  public async onModuleInit() {
    try {
      await this.emitConfigurationsAtStartup();
    } catch (error) {
      this.logger.error({
        msg: 'Failed to emit configurations at startup',
        error: sanitizeError(error),
      });
    }

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
    const tenantConfig = this.tenantConfigLoaderService.loadTenantConfig();
    const cronExpression = tenantConfig.processingScanIntervalCron;
    if (!cronExpression) {
      this.logger.warn('No cron expression configured for scheduled scan, skipping setup');
      return;
    }
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

      await this.sharepointScanner.synchronize();

      this.logger.log('SharePoint scan ended');
    } catch (error) {
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

  private async emitConfigurationsAtStartup(): Promise<void> {
    try {
      const siteConfigs = await this.tenantConfigLoaderService.loadConfig();

      if (siteConfigs.length === 0) {
        this.logger.warn(
          'No site configurations loaded. Please configure site sources via tenant config files or SharePoint list.',
        );
        return;
      }

      this.logger.log(`Loaded ${siteConfigs.length} site configuration(s) at startup`);

      for (const [index, config] of siteConfigs.entries()) {
        const redactedConfig = {
          siteId: config.siteId,
          syncColumnName: config.syncColumnName,
          ingestionMode: config.ingestionMode,
          scopeId: config.scopeId,
          maxIngestedFiles: config.maxIngestedFiles,
          storeInternally: config.storeInternally,
          syncStatus: config.syncStatus,
          inheritMode: config.inheritMode,
          syncMode: config.syncMode,
        };
        this.logger.log(
          `[Config ${index + 1}/${siteConfigs.length}]`,
          JSON.stringify(redactedConfig, null, 2),
        );
      }
    } catch (error) {
      this.logger.warn({
        msg: 'Could not emit site configurations at startup',
        error: sanitizeError(error),
      });
    }
  }
}
