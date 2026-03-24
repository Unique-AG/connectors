import { Module } from '@nestjs/common';
import { Metrics } from './metrics.service';

@Module({
  providers: [Metrics],
  exports: [Metrics],
})
export class MetricsModule {}
