import assert from 'node:assert';
import {
  type Scope,
  UNIQUE_API_CLIENT_FACTORY,
  UniqueApiClient,
  type UniqueApiClientFactory,
  type UniqueApiFeatureModuleInputOptions,
} from '@unique-ag/unique-api';
import { Inject, Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../auth/confluence-auth';
import {
  getDeletedTenantConfigs,
  getTenantConfigs,
  UniqueAuthMode,
  type UniqueConfig,
} from '../config';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../confluence-api';
import { ConfluenceContentFetcher } from '../synchronization/confluence-content-fetcher';
import { ConfluencePageScanner } from '../synchronization/confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../synchronization/confluence-synchronization.service';
import { FileDiffService } from '../synchronization/file-diff.service';
import { IngestionService } from '../synchronization/ingestion.service';
import { ScopeManagementService } from '../synchronization/scope-management.service';
import { ServiceRegistry } from './service-registry';
import type { TenantContext } from './tenant-context.interface';
import { tenantStorage } from './tenant-context.storage';

@Injectable()
export class TenantRegistry implements OnModuleInit {
  private readonly logger = new Logger(TenantRegistry.name);
  private readonly tenants = new Map<string, TenantContext>();
  private readonly deletedTenants = new Map<string, TenantContext>();

  public constructor(
    private readonly confluenceAuthFactory: ConfluenceAuthFactory,
    private readonly confluenceApiClientFactory: ConfluenceApiClientFactory,
    @Inject(UNIQUE_API_CLIENT_FACTORY) private readonly uniqueApiFactory: UniqueApiClientFactory,
    private readonly serviceRegistry: ServiceRegistry,
  ) {}

  public onModuleInit(): void {
    const tenantConfigs = getTenantConfigs();

    for (const { name: tenantName, config } of tenantConfigs) {
      const tenant: TenantContext = {
        name: tenantName,
        config,
        isScanning: false,
      };
      this.tenants.set(tenantName, tenant);

      // initialize services for the tenant
      tenantStorage.run(tenant, () => {
        this.serviceRegistry.register(
          tenantName,
          ConfluenceAuth,
          this.confluenceAuthFactory.createAuthStrategy(config.confluence),
        );
        const apiClient = this.confluenceApiClientFactory.create(config.confluence);
        this.serviceRegistry.register(tenantName, ConfluenceApiClient, apiClient);

        const scanner = new ConfluencePageScanner(config.confluence, config.processing, apiClient);
        this.serviceRegistry.register(tenantName, ConfluencePageScanner, scanner);

        const fetcher = new ConfluenceContentFetcher(config.confluence, apiClient);
        this.serviceRegistry.register(tenantName, ConfluenceContentFetcher, fetcher);

        const uniqueClient = this.uniqueApiFactory.create({
          auth: this.buildUniqueAuthConfig(config.unique),
          ingestion: {
            baseUrl: config.unique.ingestionServiceBaseUrl,
            rateLimitPerMinute: config.unique.apiRateLimitPerMinute,
          },
          scopeManagement: {
            baseUrl: config.unique.scopeManagementServiceBaseUrl,
            rateLimitPerMinute: config.unique.apiRateLimitPerMinute,
          },
          metadata: {
            clientName: 'confluence-connector',
            tenantKey: tenantName,
          },
        });

        this.serviceRegistry.register(tenantName, UniqueApiClient, uniqueClient);
        const scopeManagementService = new ScopeManagementService(
          config.ingestion,
          tenantName,
          uniqueClient,
        );
        this.serviceRegistry.register(tenantName, ScopeManagementService, scopeManagementService);

        const fileDiffService = new FileDiffService(
          config.confluence,
          tenantName,
          config.ingestion.useV1KeyFormat,
          uniqueClient,
        );
        this.serviceRegistry.register(tenantName, FileDiffService, fileDiffService);

        const ingestionService = new IngestionService(config, tenantName, uniqueClient);
        this.serviceRegistry.register(tenantName, IngestionService, ingestionService);

        const confluenceSynchronizationService = new ConfluenceSynchronizationService(
          scanner,
          fetcher,
          fileDiffService,
          ingestionService,
          scopeManagementService,
        );
        this.serviceRegistry.register(
          tenantName,
          ConfluenceSynchronizationService,
          confluenceSynchronizationService,
        );

        this.logger.log({ tenantName, msg: 'Tenant registered' });
      });
    }

    const deletedConfigs = getDeletedTenantConfigs();
    for (const { name: tenantName, config } of deletedConfigs) {
      const tenant: TenantContext = { name: tenantName, config, isScanning: false };
      this.deletedTenants.set(tenantName, tenant);

      tenantStorage.run(tenant, () => {
        const uniqueClient = this.uniqueApiFactory.create({
          auth: this.buildUniqueAuthConfig(config.unique),
          ingestion: {
            baseUrl: config.unique.ingestionServiceBaseUrl,
            rateLimitPerMinute: config.unique.apiRateLimitPerMinute,
          },
          scopeManagement: {
            baseUrl: config.unique.scopeManagementServiceBaseUrl,
            rateLimitPerMinute: config.unique.apiRateLimitPerMinute,
          },
          metadata: {
            clientName: 'confluence-connector',
            tenantKey: tenantName,
          },
        });
        this.serviceRegistry.register(tenantName, UniqueApiClient, uniqueClient);
        this.logger.log({ tenantName, msg: 'Deleted tenant registered for cleanup' });
      });
    }
  }

  public run<R>(tenant: TenantContext, fn: () => R): R {
    return tenantStorage.run(tenant, fn);
  }

  public getTenant(name: string): TenantContext {
    const tenant = this.tenants.get(name);
    assert.ok(tenant, `Unknown tenant: ${name}`);
    return tenant;
  }

  public getAllTenants(): TenantContext[] {
    return [...this.tenants.values()];
  }

  public get tenantCount(): number {
    return this.tenants.size;
  }

  public async processDeletedTenants(): Promise<void> {
    for (const tenant of this.deletedTenants.values()) {
      try {
        await this.run(tenant, async () => {
          const uniqueClient = this.serviceRegistry.getService(UniqueApiClient);
          await this.cleanupTenant(tenant, uniqueClient);
        });
      } catch (error) {
        this.logger.error({ tenantName: tenant.name, err: error, msg: 'Tenant cleanup failed' });
      }
    }
  }

  private async cleanupTenant(tenant: TenantContext, uniqueClient: UniqueApiClient): Promise<void> {
    const { scopeId, useV1KeyFormat } = tenant.config.ingestion;

    const rootScope = await uniqueClient.scopes.getById(scopeId);
    if (!rootScope) {
      this.logger.log({
        tenantName: tenant.name,
        msg: `Root scope ${scopeId} not found, skipping`,
      });
      return;
    }

    const childScopes = await uniqueClient.scopes.listChildren(scopeId);
    const fileCount = useV1KeyFormat
      ? childScopes.length
      : await uniqueClient.files.getCountByKeyPrefix(tenant.name);

    if (childScopes.length === 0 && fileCount === 0) {
      this.logger.log({ tenantName: tenant.name, msg: 'Already cleaned up, skipping' });
      return;
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

    this.logger.log({ tenantName: tenant.name, msg: 'Tenant cleanup completed' });
  }

  private async deleteFilesByScopes(scopes: Scope[], uniqueClient: UniqueApiClient): Promise<void> {
    for (const scope of scopes) {
      const fileIds = await uniqueClient.files.getFileIdsByScope(scope.id);
      if (fileIds.length > 0) {
        await uniqueClient.files.deleteByIds(fileIds);
        this.logger.log({
          scopeName: scope.name,
          deletedCount: fileIds.length,
          msg: 'Files deleted by scope ownership',
        });
      }
    }
  }

  private buildUniqueAuthConfig(
    uniqueConfig: UniqueConfig,
  ): UniqueApiFeatureModuleInputOptions['auth'] {
    switch (uniqueConfig.serviceAuthMode) {
      case UniqueAuthMode.ClusterLocal:
        return {
          serviceAuthMode: uniqueConfig.serviceAuthMode,
          serviceExtraHeaders: uniqueConfig.serviceExtraHeaders,
          serviceId: 'confluence-connector',
        };
      case UniqueAuthMode.External:
        return {
          serviceAuthMode: uniqueConfig.serviceAuthMode,
          zitadelOauthTokenUrl: uniqueConfig.zitadelOauthTokenUrl,
          zitadelClientId: uniqueConfig.zitadelClientId,
          zitadelClientSecret: uniqueConfig.zitadelClientSecret.value,
          zitadelProjectId: uniqueConfig.zitadelProjectId.value,
        };
    }
  }
}
