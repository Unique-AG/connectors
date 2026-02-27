import assert from 'node:assert';
import {
  UNIQUE_API_CLIENT_FACTORY,
  type UniqueApiClientFactory,
  type UniqueApiFeatureModuleInputOptions,
} from '@unique-ag/unique-api';
import { Inject, Injectable, type OnModuleInit } from '@nestjs/common';
import { PinoLogger } from 'nestjs-pino';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../auth/confluence-auth';
import { getTenantConfigs, UniqueAuthMode, type UniqueConfig } from '../config';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../confluence-api';
import { ConfluenceContentFetcher } from '../synchronization/confluence-content-fetcher';
import { ConfluencePageScanner } from '../synchronization/confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../synchronization/confluence-synchronization.service';
import { FileDiffService } from '../synchronization/file-diff.service';
import { IngestionService } from '../synchronization/ingestion.service';
import { ScopeManagementService } from '../synchronization/scope-management.service';
import { UniqueApiClient } from '../unique-api/types/unique-api-client.types';
import { ServiceRegistry } from './service-registry';
import type { TenantContext } from './tenant-context.interface';
import { tenantStorage } from './tenant-context.storage';

@Injectable()
export class TenantRegistry implements OnModuleInit {
  private readonly tenants = new Map<string, TenantContext>();

  public constructor(
    private readonly confluenceAuthFactory: ConfluenceAuthFactory,
    private readonly confluenceApiClientFactory: ConfluenceApiClientFactory,
    @Inject(UNIQUE_API_CLIENT_FACTORY) private readonly uniqueApiFactory: UniqueApiClientFactory,
    private readonly serviceRegistry: ServiceRegistry,
  ) {}

  public onModuleInit(): void {
    const tenantConfigs = getTenantConfigs();

    for (const { name: tenantName, config } of tenantConfigs) {
      const tenantLogger = PinoLogger.root.child({ tenantName });
      this.serviceRegistry.registerTenantLogger(tenantName, tenantLogger);

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

        const scannerLogger = this.serviceRegistry.getServiceLogger(ConfluencePageScanner);
        const scanner = new ConfluencePageScanner(
          config.confluence,
          config.processing,
          apiClient,
          scannerLogger,
        );
        this.serviceRegistry.register(tenantName, ConfluencePageScanner, scanner);

        const fetcherLogger = this.serviceRegistry.getServiceLogger(ConfluenceContentFetcher);
        const fetcher = new ConfluenceContentFetcher(config.confluence, apiClient, fetcherLogger);
        this.serviceRegistry.register(tenantName, ConfluenceContentFetcher, fetcher);

        const syncLogger = this.serviceRegistry.getServiceLogger(ConfluenceSynchronizationService);
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
        // The shared package's UniqueApiClient interface and the local abstract class have compatible
        // runtime facades but slightly divergent type definitions (e.g. UniqueFile.fileAccess).
        this.serviceRegistry.register(
          tenantName,
          UniqueApiClient,
          uniqueClient as unknown as UniqueApiClient,
        );
        const scopeManagementLogger = this.serviceRegistry.getServiceLogger(ScopeManagementService);
        const scopeManagementService = new ScopeManagementService(
          config.ingestion,
          tenantName,
          uniqueClient as unknown as UniqueApiClient,
          scopeManagementLogger,
        );
        this.serviceRegistry.register(tenantName, ScopeManagementService, scopeManagementService);

        const fileDiffService = new FileDiffService(
          config.confluence,
          config.ingestion,
          tenantName,
          this.serviceRegistry,
        );
        this.serviceRegistry.register(tenantName, FileDiffService, fileDiffService);

        const ingestionLogger = this.serviceRegistry.getServiceLogger(IngestionService);
        const ingestionService = new IngestionService(
          config.confluence,
          tenantName,
          uniqueClient as unknown as UniqueApiClient,
          ingestionLogger,
        );
        this.serviceRegistry.register(tenantName, IngestionService, ingestionService);

        this.serviceRegistry.register(
          tenantName,
          ConfluenceSynchronizationService,
          new ConfluenceSynchronizationService(
            scanner,
            fetcher,
            fileDiffService,
            ingestionService,
            scopeManagementService,
            syncLogger,
          ),
        );
      });

      tenantLogger.info('Tenant registered');
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

  private buildUniqueAuthConfig(
    uniqueConfig: UniqueConfig,
  ): UniqueApiFeatureModuleInputOptions['auth'] {
    switch (uniqueConfig.serviceAuthMode) {
      case UniqueAuthMode.CLUSTER_LOCAL:
        return {
          serviceAuthMode: uniqueConfig.serviceAuthMode,
          serviceExtraHeaders: uniqueConfig.serviceExtraHeaders,
          serviceId: 'confluence-connector',
        };
      case UniqueAuthMode.EXTERNAL:
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
