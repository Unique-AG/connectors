import { Module } from '@nestjs/common';
import { MetricService } from 'nestjs-otel';
import { KyckrConfig, kyckrConfig } from '~/config';
import { KyckrHttpClient } from './kyckr-http.client';
import { MetricsModule } from './metrics';
import { CreateDocumentOrderQuery } from './tools/create-document-order/create-document-order.query';
import { CreateDocumentOrderTool } from './tools/create-document-order/create-document-order.tool';
import { GetEnhancedProfileQuery } from './tools/get-enhanced-profile/get-enhanced-profile.query';
import { GetEnhancedProfileTool } from './tools/get-enhanced-profile/get-enhanced-profile.tool';
import { GetLiteProfileQuery } from './tools/get-lite-profile/get-lite-profile.query';
import { GetLiteProfileTool } from './tools/get-lite-profile/get-lite-profile.tool';
import { GetOrderQuery } from './tools/get-order/get-order.query';
import { GetOrderTool } from './tools/get-order/get-order.tool';
import { ListCompanyDocumentsQuery } from './tools/list-company-documents/list-company-documents.query';
import { ListCompanyDocumentsTool } from './tools/list-company-documents/list-company-documents.tool';
import { ListOrdersQuery } from './tools/list-orders/list-orders.query';
import { ListOrdersTool } from './tools/list-orders/list-orders.tool';
import { SearchCompaniesQuery } from './tools/search-companies/search-companies.query';
import { SearchCompaniesTool } from './tools/search-companies/search-companies.tool';

const QUERIES = [
  SearchCompaniesQuery,
  GetLiteProfileQuery,
  GetEnhancedProfileQuery,
  ListCompanyDocumentsQuery,
  CreateDocumentOrderQuery,
  GetOrderQuery,
  ListOrdersQuery,
];
const TOOLS = [
  SearchCompaniesTool,
  GetLiteProfileTool,
  GetEnhancedProfileTool,
  ListCompanyDocumentsTool,
  CreateDocumentOrderTool,
  GetOrderTool,
  ListOrdersTool,
];

@Module({
  imports: [MetricsModule],
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
