import { Module } from '@nestjs/common';
import { ConfluenceAuthFactory } from '../auth/confluence-auth';
import { ConfluenceApiClientFactory } from '../confluence-api';
import { ServiceRegistry } from './service-registry';
import { TenantRegistry } from './tenant-registry';

@Module({
  providers: [ConfluenceAuthFactory, ConfluenceApiClientFactory, ServiceRegistry, TenantRegistry],
  exports: [TenantRegistry, ServiceRegistry],
})
export class TenantModule {}
