import { Injectable, Logger, type OnModuleDestroy, type OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import type { TenantContext } from '../tenant/tenant-context.interface';
import { tenantStorage } from '../tenant/tenant-context.storage';
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
    // Guard: TenantRegistry.onModuleInit must run before this — ensured by
    // importing TenantModule before SchedulerModule in AppModule.imports.
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
    const cronExpression = tenant.config.processing.scanIntervalCron;
    const job = new CronJob(cronExpression, () => {
      void this.syncTenant(tenant);
    });
    this.schedulerRegistry.addCronJob(`sync:${tenant.name}`, job);
    job.start();
    tenant.logger.log(`Scheduled sync with cron: ${cronExpression}`);
  }

  private async syncTenant(tenant: TenantContext): Promise<void> {
    if (this.isShuttingDown) {
      tenant.logger.log('Skipping sync due to shutdown');
      return;
    }

    if (tenant.isScanning) {
      tenant.logger.log('Sync already in progress, skipping');
      return;
    }

    tenant.isScanning = true;
    try {
      await tenantStorage.run(tenant, async () => {
        tenant.logger.log('Starting sync');
        const token = await tenant.auth.getAccessToken();
        tenant.logger.log(`Token acquired successfully (${smear(token)})`);
        // TODO: Full sync pipeline
      });
    } catch (error) {
      tenant.logger.error({
        msg: 'Sync failed',
        error: sanitizeError(error),
      });
    } finally {
      tenant.isScanning = false;
    }
  }
}
