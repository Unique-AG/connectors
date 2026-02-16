import { Injectable, Logger, type OnModuleInit } from '@nestjs/common';
import { getTenantConfigs } from '../config/tenant-config-loader';
import { TenantAuthFactory } from './tenant-auth.factory';
import type { TenantContext } from './tenant-context.interface';

@Injectable()
export class TenantRegistry implements OnModuleInit {
  private readonly tenants = new Map<string, TenantContext>();

  public constructor(private readonly authFactory: TenantAuthFactory) {}

  public onModuleInit(): void {
    const configs = getTenantConfigs();
    for (const { name, config } of configs) {
      const tenantLogger = new Logger(`Tenant:${name}`);
      this.tenants.set(name, {
        name,
        config,
        logger: tenantLogger,
        auth: this.authFactory.create(config.confluence),
        isScanning: false,
      });
      tenantLogger.log('Tenant registered');
    }
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
