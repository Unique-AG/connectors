import { Module } from '@nestjs/common';
import { TerminusModule } from '@nestjs/terminus';
import { ProxyModule } from '../proxy';
import { TenantModule } from '../tenant';
import { ConnectivityHealthIndicator } from './connectivity-health.indicator';
import { HealthController } from './health.controller';
import { SyncHealthIndicator } from './sync-health.indicator';
import { SyncStatusStore } from './sync-status.store';
import { UniqueApiHealthIndicator } from './unique-api-health.indicator';

@Module({
  imports: [TerminusModule, ProxyModule, TenantModule],
  controllers: [HealthController],
  providers: [
    SyncStatusStore,
    SyncHealthIndicator,
    ConnectivityHealthIndicator,
    UniqueApiHealthIndicator,
  ],
  exports: [SyncStatusStore],
})
export class HealthModule {}
