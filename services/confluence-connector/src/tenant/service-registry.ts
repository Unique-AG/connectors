import assert from 'node:assert';
import { Injectable } from '@nestjs/common';
import type pino from 'pino';
import { getCurrentTenant } from './tenant-context.storage';

export type AbstractClass<T> = abstract new (...args: unknown[]) => T;

interface ServiceClass {
  readonly name: string;
}

@Injectable()
export class ServiceRegistry {
  // biome-ignore lint/complexity/noBannedTypes: Function is used as runtime map key for abstract class constructors
  private readonly tenantServices = new Map<string, Map<Function, unknown>>();
  private readonly tenantLoggers = new Map<string, pino.Logger>();

  public register<T>(tenantName: string, key: AbstractClass<T>, instance: T): void {
    let services = this.tenantServices.get(tenantName);

    if (!services) {
      services = new Map();
      this.tenantServices.set(tenantName, services);
    }

    services.set(key, instance);
  }

  public registerTenantLogger(tenantName: string, logger: pino.Logger): void {
    this.tenantLoggers.set(tenantName, logger);
  }

  public getServiceLogger(service: ServiceClass): pino.Logger {
    const tenant = getCurrentTenant();
    const baseLogger = this.tenantLoggers.get(tenant.name);
    assert.ok(baseLogger, `No logger registered for tenant: ${tenant.name}`);
    return baseLogger.child({ service: service.name });
  }

  public getService<T>(key: AbstractClass<T>): T {
    const tenant = getCurrentTenant();
    const services = this.getTenantServices(tenant.name);
    const instance = services.get(key);

    assert.ok(instance, `Service not found for tenant "${tenant.name}": ${key.name}`);
    return instance as T;
  }

  // biome-ignore lint/complexity/noBannedTypes: Function is used as runtime map key for abstract class constructors
  private getTenantServices(tenantName: string): Map<Function, unknown> {
    const services = this.tenantServices.get(tenantName);
    assert.ok(services, `No services registered for tenant: ${tenantName}`);
    return services;
  }
}
