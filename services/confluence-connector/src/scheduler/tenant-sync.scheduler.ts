import { Injectable, Logger, type OnModuleDestroy, type OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import type { TenantContext } from '../tenant/tenant-context.interface';
import { tenantStorage } from '../tenant/tenant-context.storage';
import { getTenantLogger } from '../tenant/tenant-logger';
import { TenantRegistry } from '../tenant/tenant-registry';
import { smear } from '../utils/logging.util';
import { sanitizeError } from '../utils/normalize-error';

@Injectable()
export class TenantSyncScheduler implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(TenantSyncScheduler.name);
  private isShuttingDown = false;

  public constructor(
    private readonly tenantRegistry: TenantRegistry,
    private readonly schedulerRegistry: SchedulerRegistry,
  ) {}

  public onModuleInit(): void {
    if (this.tenantRegistry.size === 0) {
      this.logger.warn('No tenants registered — no sync jobs will be scheduled');
      return;
    }

    for (const tenant of this.tenantRegistry.getAll()) {
      this.logger.log(`Triggering initial sync for tenant: ${tenant.name}`);
      void this.syncTenant(tenant);
      this.registerCronJob(tenant);
    }
  }

  public onModuleDestroy(): void {
    this.logger.log('Shutting down tenant sync scheduler');
    this.isShuttingDown = true;
    try {
      for (const [name, job] of this.schedulerRegistry.getCronJobs()) {
        this.logger.log(`Stopping cron job: ${name}`);
        job.stop();
      }
    } catch (error) {
      this.logger.error({
        msg: 'Error stopping cron jobs',
        error: sanitizeError(error),
      });
    }
  }

  private registerCronJob(tenant: TenantContext): void {
    tenantStorage.run(tenant, () => {
      const logger = getTenantLogger(TenantSyncScheduler);
      const cronExpression = tenant.config.processing.scanIntervalCron;
      const job = new CronJob(cronExpression, () => {
        void this.syncTenant(tenant);
      });
      this.schedulerRegistry.addCronJob(`sync:${tenant.name}`, job);
      job.start();
      logger.info(`Scheduled sync with cron: ${cronExpression}`);
    });
  }

  private async syncTenant(tenant: TenantContext): Promise<void> {
    await tenantStorage.run(tenant, async () => {
      const logger = getTenantLogger(TenantSyncScheduler);

      if (this.isShuttingDown) {
        logger.info('Skipping sync due to shutdown');
        return;
      }

      if (tenant.isScanning) {
        logger.info('Sync already in progress, skipping');
        return;
      }

      tenant.isScanning = true;
      try {
        logger.info('Starting sync');
        const token = await tenant.auth.getAccessToken();
        logger.info({ token: smear(token) }, 'Token acquired');
        // TODO: Full sync pipeline
      } catch (error) {
        logger.error({
          msg: 'Sync failed',
          error: sanitizeError(error),
        });
      } finally {
        tenant.isScanning = false;
      }
    });
  }
}
