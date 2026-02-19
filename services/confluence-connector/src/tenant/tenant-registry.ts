import assert from 'node:assert';
import { Injectable, type OnModuleInit } from '@nestjs/common';
import { PinoLogger } from 'nestjs-pino';
import { ConfluenceAuth, ConfluenceAuthFactory } from '../auth/confluence-auth';
import { UniqueAuth, UniqueAuthFactory } from '../auth/unique-auth';
import { getTenantConfigs } from '../config';
import { ConfluenceApiClient, ConfluenceApiClientFactory } from '../confluence-api';
import { ConfluenceContentFetcher } from '../synchronization/confluence-content-fetcher';
import { ConfluencePageScanner } from '../synchronization/confluence-page-scanner';
import { ConfluenceSynchronizationService } from '../synchronization/confluence-synchronization.service';
import { FileDiffService } from '../synchronization/file-diff.service';
import { IngestionService } from '../synchronization/ingestion.service';
import { MockUniqueApiClient } from '../unique-api/mock-unique-api-client';
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
    private readonly uniqueAuthFactory: UniqueAuthFactory,
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
        this.serviceRegistry.register(
          tenantName,
          UniqueAuth,
          this.uniqueAuthFactory.create(config.unique),
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
        this.serviceRegistry.register(
          tenantName,
          UniqueApiClient,
          new MockUniqueApiClient(tenantLogger),
        );
        this.serviceRegistry.register(
          tenantName,
          FileDiffService,
          new FileDiffService(config.confluence, config.ingestion, this.serviceRegistry),
        );
        this.serviceRegistry.register(
          tenantName,
          IngestionService,
          new IngestionService(config.confluence, config.ingestion, this.serviceRegistry),
        );
        this.serviceRegistry.register(
          tenantName,
          ConfluenceSynchronizationService,
          new ConfluenceSynchronizationService(scanner, fetcher, syncLogger),
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
}
