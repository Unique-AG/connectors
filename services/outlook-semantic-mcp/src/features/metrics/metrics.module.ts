import { Module } from '@nestjs/common';
import { SyncMetricsService } from './sync-metrics.service';

@Module({
  providers: [SyncMetricsService],
  exports: [SyncMetricsService],
})
export class MetricsModule {}
