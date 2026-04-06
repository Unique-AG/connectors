import { UniqueApiClient } from '@unique-ag/unique-api';
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
      this.logger.warn({ msg: 'No active tenants registered — no sync jobs will be scheduled' });
      // Still process deleted tenants even without active tenants
      void this.processDeletedTenants();
      return;
    }

    for (const tenant of this.tenantRegistry.getAllTenants()) {
      this.logger.log({ tenantName: tenant.name, msg: 'Triggering initial sync' });
      void this.syncTenant(tenant);
      this.registerCronJob(tenant);
    }
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
        msg: `Scheduled sync with cron: ${cronExpression}`,
      });
    });
  }

  private async syncTenant(tenant: TenantContext): Promise<void> {
    if (this.isShuttingDown) {
      this.tenantRegistry.run(tenant, () => {
        this.logger.log({ msg: 'Skipping sync due to shutdown' });
      });
      return;
    }

    await this.processDeletedTenants();

    await this.tenantRegistry.run(tenant, async () => {
      const syncService = this.serviceRegistry.getService(ConfluenceSynchronizationService);

      try {
        await syncService.synchronize();
      } catch (error) {
        this.logger.error({ err: error, msg: 'Unexpected sync error' });
      }
    });
  }

  private async processDeletedTenants(): Promise<void> {
    for (const tenant of this.tenantRegistry.getDeletedTenants()) {
      await this.tenantRegistry.run(tenant, () => this.cleanupTenant(tenant));
    }
  }

  private async cleanupTenant(tenant: TenantContext): Promise<void> {
    const uniqueClient = this.serviceRegistry.getService(UniqueApiClient);
    const { scopeId, useV1KeyFormat } = tenant.config.ingestion;

    try {
      this.logger.log({ tenantName: tenant.name, msg: 'Starting cleanup' });

      const rootScope = await uniqueClient.scopes.getById(scopeId);
      if (!rootScope) {
        this.logger.log({
          tenantName: tenant.name,
          msg: `Root scope ${scopeId} not found, skipping`,
        });
        return;
      }

      const childScopes = await uniqueClient.scopes.listChildren(scopeId);

      if (!useV1KeyFormat) {
        const fileCount = await uniqueClient.files.getCountByKeyPrefix(tenant.name);
        if (childScopes.length === 0 && fileCount === 0) {
          this.logger.log({ tenantName: tenant.name, msg: 'Already cleaned up, skipping' });
          return;
        }
      } else {
        if (childScopes.length === 0) {
          this.logger.log({ tenantName: tenant.name, msg: 'Already cleaned up, skipping' });
          return;
        }
      }

      if (useV1KeyFormat) {
        await this.deleteFilesByScopes(childScopes, uniqueClient);
      } else {
        const deletedCount = await uniqueClient.files.deleteByKeyPrefix(tenant.name);
        this.logger.log({
          tenantName: tenant.name,
          deletedCount,
          msg: 'Files deleted by key prefix',
        });
      }

      for (const child of childScopes) {
        const result = await uniqueClient.scopes.delete(child.id, { recursive: true });
        this.logger.log({
          tenantName: tenant.name,
          scopeName: child.name,
          succeeded: result.successFolders.length,
          failed: result.failedFolders.length,
          msg: 'Child scope deleted',
        });
      }

      this.logger.log({ tenantName: tenant.name, msg: 'Cleanup completed' });
    } catch (error) {
      this.logger.error({
        tenantName: tenant.name,
        err: error,
        msg: 'Cleanup failed, will retry on next cycle',
      });
    }
  }

  private async deleteFilesByScopes(
    scopes: { id: string; name: string; externalId: string | null }[],
    uniqueClient: UniqueApiClient,
  ): Promise<void> {
    for (const scope of scopes) {
      const files = await uniqueClient.files.getByKeyPrefix(scope.externalId ?? scope.name);
      if (files.length > 0) {
        const ids = files.map((f) => f.id);
        await uniqueClient.files.deleteByIds(ids);
        this.logger.log({
          scopeName: scope.name,
          deletedCount: ids.length,
          msg: 'Files deleted by scope ownership',
        });
      }
    }
  }
}
