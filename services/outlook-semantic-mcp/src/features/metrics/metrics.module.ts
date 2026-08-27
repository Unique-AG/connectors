import { Module } from '@nestjs/common';
import { CalendarMetricsService } from './calendar-metrics.service';
import { DelegatedAccessMetricsService } from './delegated-access-metrics.service';
import { SyncMetricsService } from './sync-metrics.service';

@Module({
  providers: [SyncMetricsService, DelegatedAccessMetricsService, CalendarMetricsService],
  exports: [SyncMetricsService, DelegatedAccessMetricsService, CalendarMetricsService],
})
export class MetricsModule {}
