import { Module } from '@nestjs/common';
import { A2aServerModule } from './a2a-server/a2a-server.module.js';
import { GatewayConfigModule } from './config/config.module.js';
import { HealthModule } from './health/health.module.js';
import { InternalModule } from './internal/internal.module.js';
import { ManagementModule } from './management/management.module.js';

@Module({
  imports: [GatewayConfigModule, A2aServerModule, ManagementModule, InternalModule, HealthModule],
})
export class AppModule {}
