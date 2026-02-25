import assert from 'node:assert';
import { Injectable } from '@nestjs/common';
import type pino from 'pino';
import { getCurrentTenant } from './tenant-context.storage';

// biome-ignore lint/suspicious/noExplicitAny: Constructor args are irrelevant — these types are used only as Map keys for service lookup
export type AbstractClass<T> = abstract new (...args: any[]) => T;
// biome-ignore lint/suspicious/noExplicitAny: Constructor args are irrelevant — these types are used only as Map keys for service lookup
type ConcreteClass<T> = new (...args: any[]) => T;
export type ServiceToken<T> = AbstractClass<T> | ConcreteClass<T>;

interface ServiceClass {
  readonly name: string;
}

@Injectable()
export class ServiceRegistry {
  private readonly tenantServices = new Map<string, Map<ServiceToken<unknown>, unknown>>();
  private readonly tenantLoggers = new Map<string, pino.Logger>();

  public register<T>(tenantName: string, key: ServiceToken<T>, instance: T): void {
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
    return baseLogger.child({ tenantName: tenant.name, service: service.name });
  }

  public getService<T>(key: ServiceToken<T>): T {
    const tenant = getCurrentTenant();
    const services = this.getTenantServices(tenant.name);
    const instance = services.get(key);

    assert.ok(instance, `Service not found for tenant "${tenant.name}": ${key.name}`);
    return instance as T;
  }

  private getTenantServices(tenantName: string): Map<ServiceToken<unknown>, unknown> {
    const services = this.tenantServices.get(tenantName);
    assert.ok(services, `No services registered for tenant: ${tenantName}`);
    return services;
  }
}
