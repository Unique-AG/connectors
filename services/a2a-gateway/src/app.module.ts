import { Module } from '@nestjs/common';
import { A2aServerModule } from './a2a-server/a2a-server.module.js';
import { GatewayConfigModule } from './config/config.module.js';
import { PersistenceModule } from './drizzle/persistence.module.js';
import { HealthModule } from './health/health.module.js';
import { InternalModule } from './internal/internal.module.js';
import { LifecycleModule } from './lifecycle/lifecycle.module.js';
import { ManagementModule } from './management/management.module.js';
import { ObservabilityModule } from './observability/observability.module.js';
import { OutboundModule } from './outbound/outbound.module.js';
import { UniqueModule } from './unique/unique.module.js';

@Module({
  imports: [
    GatewayConfigModule,
    ObservabilityModule,
    PersistenceModule,
    UniqueModule,
    A2aServerModule,
    ManagementModule,
    InternalModule,
    OutboundModule,
    LifecycleModule,
    HealthModule,
  ],
})
export class AppModule {}
