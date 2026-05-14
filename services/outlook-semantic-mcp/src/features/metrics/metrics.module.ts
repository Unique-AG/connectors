import { Module } from '@nestjs/common';
import { DelegatedAccessMetricsService } from './delegated-access-metrics.service';
import { SyncMetricsService } from './sync-metrics.service';

@Module({
  providers: [SyncMetricsService, DelegatedAccessMetricsService],
  exports: [SyncMetricsService, DelegatedAccessMetricsService],
})
export class MetricsModule {}
