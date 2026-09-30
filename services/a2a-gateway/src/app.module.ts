import { Module } from '@nestjs/common';
import { A2aServerModule } from './a2a-server/a2a-server.module.js';
import { GatewayConfigModule } from './config/config.module.js';
import { PersistenceModule } from './drizzle/persistence.module.js';
import { HealthModule } from './health/health.module.js';
import { InternalModule } from './internal/internal.module.js';
import { ManagementModule } from './management/management.module.js';
import { OutboundModule } from './outbound/outbound.module.js';
import { UniqueModule } from './unique/unique.module.js';

@Module({
  imports: [
    GatewayConfigModule,
    PersistenceModule,
    UniqueModule,
    A2aServerModule,
    ManagementModule,
    InternalModule,
    OutboundModule,
    HealthModule,
  ],
})
export class AppModule {}
