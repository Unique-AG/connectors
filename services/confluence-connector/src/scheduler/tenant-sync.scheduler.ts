import { Injectable, Logger, type OnModuleDestroy, type OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { ConfluenceSynchronizationService } from '../synchronization/confluence-synchronization.service';
import type { TenantContext } from '../tenant';
import { ServiceRegistry, TenantRegistry } from '../tenant';

@Injectable()
export class TenantSyncScheduler implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(TenantSyncScheduler.name);
  private isShuttingDown = false;

  public constructor(
    private readonly tenantRegistry: TenantRegistry,
    private readonly serviceRegistry: ServiceRegistry,
    private readonly schedulerRegistry: SchedulerRegistry,
  ) {}

  public onModuleInit(): void {
    if (this.tenantRegistry.tenantCount === 0) {
      this.logger.warn('No tenants registered — no sync jobs will be scheduled');
      return;
    }

    for (const tenant of this.tenantRegistry.getAllTenants()) {
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
        error,
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

    this.tenantRegistry.run(tenant, () => {
      const logger = this.serviceRegistry.getServiceLogger(TenantSyncScheduler);
      logger.info(`Scheduled sync with cron: ${cronExpression}`);
    });
  }

  // services are resolved per-call because TenantSyncScheduler is a single instance for all tenants so we can't set services in the constructor
  private async syncTenant(tenant: TenantContext): Promise<void> {
    await this.tenantRegistry.run(tenant, async () => {
      const logger = this.serviceRegistry.getServiceLogger(TenantSyncScheduler);
      const syncService = this.serviceRegistry.getService(ConfluenceSynchronizationService);

      if (this.isShuttingDown) {
        logger.info('Skipping sync due to shutdown');
        return;
      }

      try {
        await syncService.synchronize();
      } catch (error) {
        logger.error({
          msg: 'Unexpected sync error',
          error,
        });
      }
    });
  }
}
