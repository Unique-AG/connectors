import { Module } from '@nestjs/common';
import { ConfluenceAuthFactory } from '../auth/confluence-auth';
import { ConfluenceApiClientFactory } from '../confluence-api';
import { MetricsModule } from '../metrics';
import { ServiceRegistry } from './service-registry';
import { TenantRegistry } from './tenant-registry';

@Module({
  imports: [MetricsModule],
  providers: [ConfluenceAuthFactory, ConfluenceApiClientFactory, ServiceRegistry, TenantRegistry],
  exports: [TenantRegistry, ServiceRegistry],
})
export class TenantModule {}
