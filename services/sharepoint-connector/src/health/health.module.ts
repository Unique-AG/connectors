import { Module } from '@nestjs/common';
import { TerminusModule } from '@nestjs/terminus';
import { UniqueApiModule } from '../unique-api/unique-api.module';
import { ConnectivityHealthIndicator } from './connectivity-health.indicator';
import { HealthController } from './health.controller';
import { SyncHealthIndicator } from './sync-health.indicator';
import { SyncStatusStore } from './sync-status.store';
import { UniqueApiHealthIndicator } from './unique-api-health.indicator';

@Module({
  imports: [TerminusModule, UniqueApiModule],
  controllers: [HealthController],
  providers: [SyncStatusStore, SyncHealthIndicator, ConnectivityHealthIndicator, UniqueApiHealthIndicator],
  exports: [SyncStatusStore],
})
export class HealthModule {}
