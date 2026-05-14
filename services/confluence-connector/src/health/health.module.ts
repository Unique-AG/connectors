import { Module } from '@nestjs/common';
import { TerminusModule } from '@nestjs/terminus';
import { ProxyModule } from '../proxy';
import { TenantModule } from '../tenant';
import { HealthController } from './health.controller';
import { MsGraphConnectivityHealthIndicator } from './ms-graph-connectivity-health.indicator';
import { SyncHealthIndicator } from './sync-health.indicator';
import { SyncStatusStore } from './sync-status.store';
import { UniqueApiHealthIndicator } from './unique-api-health.indicator';

@Module({
  imports: [TerminusModule, ProxyModule, TenantModule],
  controllers: [HealthController],
  providers: [
    SyncStatusStore,
    SyncHealthIndicator,
    MsGraphConnectivityHealthIndicator,
    UniqueApiHealthIndicator,
  ],
  exports: [SyncStatusStore],
})
export class HealthModule {}
