import { Injectable, Logger, type OnModuleDestroy, type OnModuleInit } from '@nestjs/common';
import { SchedulerRegistry } from '@nestjs/schedule';
import { CronJob } from 'cron';
import { ConfluenceSynchronizationService } from '../synchronization/confluence-synchronization.service';
import type { TenantContext } from '../tenant';
import { ServiceRegistry, TenantDeleteService, TenantRegistry } from '../tenant';

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
    this.scheduleTenantJobs();
  }

  public onModuleDestroy(): void {
    this.logger.log({ msg: 'Shutting down tenant sync scheduler' });
    this.isShuttingDown = true;
    try {
      for (const [name, job] of this.schedulerRegistry.getCronJobs()) {
        this.logger.log({ msg: `Stopping cron job: ${name}` });
        job.stop();
      }
    } catch (error) {
      this.logger.error({ err: error, msg: 'Error stopping cron jobs' });
    }
  }

  private scheduleTenantJobs(): void {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Shutdown in progress, skipping job scheduling' });
      return;
    }

    if (this.tenantRegistry.tenantCount === 0) {
      this.logger.warn({ msg: 'No tenants registered — no jobs will be scheduled' });
      return;
    }

    for (const tenant of this.tenantRegistry.getAllTenants()) {
      this.logger.log({ tenantName: tenant.name, msg: 'Triggering initial job' });
      void this.syncTenant(tenant);
      this.registerCronJob(tenant);
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
      this.logger.log({
        tenantName: tenant.name,
        msg: `Scheduled job with cron: ${cronExpression}`,
      });
    });
  }

  private async syncTenant(tenant: TenantContext): Promise<void> {
    if (this.isShuttingDown) {
      this.logger.log({ msg: 'Skipping job due to shutdown' });
      return;
    }

    if (tenant.isScanning) {
      this.logger.log({ tenantName: tenant.name, msg: 'Job already in progress, skipping' });
      return;
    }

    tenant.isScanning = true;
    try {
      await this.tenantRegistry.run(tenant, async () => {
        if (tenant.status === 'deleted') {
          const deleteService = this.serviceRegistry.getService(TenantDeleteService);
          await deleteService.deleteTenantContent();
          return;
        }

        const syncService = this.serviceRegistry.getService(ConfluenceSynchronizationService);
        await syncService.synchronize();
      });
    } catch (error) {
      this.logger.error({
        tenantName: tenant.name,
        err: error,
        msg: 'Unexpected error in tenant job',
      });
    } finally {
      tenant.isScanning = false;
    }
  }
}
