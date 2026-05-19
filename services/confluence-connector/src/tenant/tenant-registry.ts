import assert from 'node:assert';
import {
  UNIQUE_API_CLIENT_FACTORY,
  UniqueApiClient,
  type UniqueApiClientFactory,
  type UniqueApiFeatureModuleInputOptions,
} from '@unique-ag/unique-api';
import { Inject, Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../auth/confluence-auth';
import {
  getTenantConfigs,
  type TenantConfig,
  TenantStatus,
  UniqueAuthMode,
  type UniqueConfig,
} from '../config';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../confluence-api';
import { Metrics } from '../metrics';
import { ProxyService } from '../proxy';
import { ConfluenceContentFetcher } from '../synchronization/confluence-content-fetcher';
import { ConfluencePageScanner } from '../synchronization/confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../synchronization/confluence-synchronization.service';
import { FileDiffService } from '../synchronization/file-diff.service';
import { IngestionService } from '../synchronization/ingestion.service';
import { PageImageInliner } from '../synchronization/page-image-inliner';
import { RootScopeMigrationService } from '../synchronization/root-scope-migration.service';
import { ScopeManagementService } from '../synchronization/scope-management.service';
import { ServiceRegistry } from './service-registry';
import type { TenantContext } from './tenant-context.interface';
import { tenantStorage } from './tenant-context.storage';
import { TenantDeleteService } from './tenant-delete.service';

@Injectable()
export class TenantRegistry implements OnModuleInit {
  private readonly logger = new Logger(TenantRegistry.name);
  private readonly tenants = new Map<string, TenantContext>();

  public constructor(
    private readonly confluenceAuthFactory: ConfluenceAuthFactory,
    private readonly confluenceApiClientFactory: ConfluenceApiClientFactory,
    @Inject(UNIQUE_API_CLIENT_FACTORY) private readonly uniqueApiFactory: UniqueApiClientFactory,
    private readonly serviceRegistry: ServiceRegistry,
    private readonly proxyService: ProxyService,
    private readonly metrics: Metrics,
  ) {}

  public onModuleInit(): void {
    for (const { name: tenantName, config, status } of getTenantConfigs()) {
      const tenant: TenantContext = { name: tenantName, config, status, isScanning: false };
      this.tenants.set(tenantName, tenant);

      tenantStorage.run(tenant, () => {
        const uniqueClient = this.createUniqueApiClient(tenantName, config.unique);
        this.serviceRegistry.register(tenantName, UniqueApiClient, uniqueClient);

        if (status === TenantStatus.Deleted) {
          this.registerDeletedTenantServices(tenantName, config, uniqueClient);
        } else {
          this.registerActiveTenantServices(tenantName, config, uniqueClient);
        }
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

  private createUniqueApiClient(tenantName: string, uniqueConfig: UniqueConfig): UniqueApiClient {
    const isExternal = uniqueConfig.serviceAuthMode === UniqueAuthMode.External;
    const dispatcher = this.proxyService.getDispatcher({
      mode: isExternal ? 'always' : 'never',
    });

    return this.uniqueApiFactory.create({
      auth: this.buildUniqueAuthConfig(uniqueConfig),
      dispatcher,
      ingestion: {
        baseUrl: uniqueConfig.ingestionServiceBaseUrl,
        rateLimitPerMinute: uniqueConfig.apiRateLimitPerMinute,
      },
      scopeManagement: {
        baseUrl: uniqueConfig.scopeManagementServiceBaseUrl,
        rateLimitPerMinute: uniqueConfig.apiRateLimitPerMinute,
      },
      metadata: {
        clientName: 'confluence-connector',
        tenantKey: tenantName,
      },
    });
  }

  private registerDeletedTenantServices(
    tenantName: string,
    config: TenantConfig,
    uniqueClient: UniqueApiClient,
  ): void {
    const cleanupService = new TenantDeleteService(
      tenantName,
      config.ingestion.scopeId,
      uniqueClient,
      this.metrics,
    );
    this.serviceRegistry.register(tenantName, TenantDeleteService, cleanupService);
    this.metrics.initializeCleanupCounters();
    this.logger.log({ tenantName, msg: 'Deleted tenant registered for cleanup' });
  }

  private registerActiveTenantServices(
    tenantName: string,
    config: TenantConfig,
    uniqueClient: UniqueApiClient,
  ): void {
    this.serviceRegistry.register(
      tenantName,
      ConfluenceAuth,
      this.confluenceAuthFactory.createAuthStrategy(config.confluence),
    );

    const apiClient = this.confluenceApiClientFactory.create(
      config.confluence,
      { attachmentsEnabled: config.ingestion.attachments.enabled },
      this.metrics,
    );
    this.serviceRegistry.register(tenantName, ConfluenceApiClient, apiClient);

    const scanner = new ConfluencePageScanner(
      config.confluence,
      config.processing,
      apiClient,
      config.ingestion.attachments,
    );
    this.serviceRegistry.register(tenantName, ConfluencePageScanner, scanner);

    const fetcher = new ConfluenceContentFetcher(config.confluence, apiClient);
    this.serviceRegistry.register(tenantName, ConfluenceContentFetcher, fetcher);

    const fileDiffService = new FileDiffService(
      config.confluence,
      tenantName,
      config.ingestion.useV1KeyFormat,
      uniqueClient,
      this.metrics,
    );
    this.serviceRegistry.register(tenantName, FileDiffService, fileDiffService);

    const isExternal = config.unique.serviceAuthMode === UniqueAuthMode.External;
    const blobUploadDispatcher = this.proxyService.getDispatcher({
      mode: isExternal ? 'always' : 'never',
    });
    const ingestionService = new IngestionService(
      config,
      tenantName,
      uniqueClient,
      apiClient,
      this.metrics,
      blobUploadDispatcher,
    );
    this.serviceRegistry.register(tenantName, IngestionService, ingestionService);

    const pageImageInliner = new PageImageInliner(config, apiClient);
    this.serviceRegistry.register(tenantName, PageImageInliner, pageImageInliner);

    const rootScopeMigrationService = new RootScopeMigrationService(uniqueClient);
    const scopeManagementService = new ScopeManagementService(
      config.ingestion,
      tenantName,
      apiClient,
      uniqueClient,
      this.metrics,
      rootScopeMigrationService,
    );
    this.serviceRegistry.register(tenantName, ScopeManagementService, scopeManagementService);

    const syncService = new ConfluenceSynchronizationService(
      scanner,
      fetcher,
      fileDiffService,
      ingestionService,
      pageImageInliner,
      scopeManagementService,
      this.metrics,
    );
    this.serviceRegistry.register(tenantName, ConfluenceSynchronizationService, syncService);

    this.metrics.initializeCounters();
    this.logger.log({ tenantName, msg: 'Tenant registered' });
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
