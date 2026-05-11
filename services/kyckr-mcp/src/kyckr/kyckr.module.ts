import { Module } from '@nestjs/common';
import { MetricService } from 'nestjs-otel';
import { KyckrConfig, kyckrConfig } from '~/config';
import { KyckrHttpClient } from './kyckr-http.client';
import { SearchCompaniesQuery } from './tools/search-companies/search-companies.query';
import { SearchCompaniesTool } from './tools/search-companies/search-companies.tool';

const QUERIES = [SearchCompaniesQuery];
const TOOLS = [SearchCompaniesTool];

@Module({
  providers: [
    {
      provide: KyckrHttpClient,
      inject: [kyckrConfig.KEY, MetricService],
      useFactory: (config: KyckrConfig, metricService: MetricService) =>
        new KyckrHttpClient(config, metricService),
    },
    ...QUERIES,
    ...TOOLS,
  ],
  exports: [KyckrHttpClient, ...QUERIES, ...TOOLS],
})
export class KyckrModule {}
