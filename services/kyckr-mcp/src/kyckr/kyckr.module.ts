import { Module } from '@nestjs/common';
import { MetricService } from 'nestjs-otel';
import { KyckrConfig, kyckrConfig } from '../config';
import { KyckrHttpClient } from './kyckr-http.client';

@Module({
  providers: [
    {
      provide: KyckrHttpClient,
      inject: [kyckrConfig.KEY, MetricService],
      useFactory: (config: KyckrConfig, metricService: MetricService) =>
        new KyckrHttpClient(config, metricService),
    },
  ],
  exports: [KyckrHttpClient],
})
export class KyckrModule {}
