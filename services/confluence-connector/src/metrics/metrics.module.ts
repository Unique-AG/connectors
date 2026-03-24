import { Module } from '@nestjs/common';
import { ConfConMetrics } from './conf-con-metrics';

@Module({
  providers: [ConfConMetrics],
  exports: [ConfConMetrics],
})
export class MetricsModule {}
