import { Module } from '@nestjs/common';
import { ConfluenceAuthFactory } from '../auth/confluence-auth';
import { UniqueAuthFactory } from '../auth/unique-auth';
import { ServiceRegistry } from './service-registry';
import { TenantRegistry } from './tenant-registry';

@Module({
  providers: [ConfluenceAuthFactory, UniqueAuthFactory, ServiceRegistry, TenantRegistry],
  exports: [TenantRegistry, ServiceRegistry],
})
export class TenantModule {}
