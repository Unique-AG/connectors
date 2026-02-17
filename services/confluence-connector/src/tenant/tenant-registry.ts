import { Injectable, Logger, type OnModuleDestroy, type OnModuleInit } from '@nestjs/common';
import { PinoLogger } from 'nestjs-pino';
import { getTenantConfigs } from '../config/tenant-config-loader';
import { UniqueServiceAuth, UniqueTenantAuthFactory } from '../unique-auth';
import { ConfluenceTenantAuthFactory } from './confluence-tenant-auth.factory';
import { TenantAuth } from './tenant-auth';
import type { TenantContext } from './tenant-context.interface';
import { TenantServiceRegistry } from './tenant-service-registry';

@Injectable()
export class TenantRegistry implements OnModuleInit, OnModuleDestroy {
  private readonly logger = new Logger(TenantRegistry.name);
  private readonly tenants = new Map<string, TenantContext>();

  public constructor(
    private readonly confluenceAuthFactory: ConfluenceTenantAuthFactory,
    private readonly uniqueAuthFactory: UniqueTenantAuthFactory,
  ) {}

  public onModuleInit(): void {
    const configs = getTenantConfigs();
    for (const { name, config } of configs) {
      const tenantLogger = PinoLogger.root.child({ tenantName: name });

      const services = new TenantServiceRegistry()
        .set(TenantAuth, this.confluenceAuthFactory.create(config.confluence))
        .set(UniqueServiceAuth, this.uniqueAuthFactory.create(config.unique));

      this.tenants.set(name, {
        name,
        config,
        services,
        logger: tenantLogger,
        isScanning: false,
      });
      tenantLogger.info('Tenant registered');
    }
  }

  public async onModuleDestroy(): Promise<void> {
    const closePromises = this.getAll().map(async (tenant) => {
      try {
        await tenant.services.get(UniqueServiceAuth).close();
      } catch (error) {
        this.logger.error({
          msg: `Failed to close UniqueServiceAuth for tenant ${tenant.name}`,
          error,
        });
      }
    });
    await Promise.all(closePromises);
  }

  public get(name: string): TenantContext {
    const tenant = this.tenants.get(name);
    if (!tenant) throw new Error(`Unknown tenant: ${name}`);
    return tenant;
  }

  public getAll(): TenantContext[] {
    return [...this.tenants.values()];
  }

  public get size(): number {
    return this.tenants.size;
  }
}
