import { PinoLogger } from 'nestjs-pino';
import type pino from 'pino';
import { getCurrentTenant } from './tenant-context.storage';

interface ServiceClass {
  readonly name: string;
}

export function getTenantLogger(service: ServiceClass): pino.Logger {
  const tenant = getCurrentTenant();
  return PinoLogger.root.child({ tenantName: tenant.name, service: service.name });
}
