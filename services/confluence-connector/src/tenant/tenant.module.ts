import { Global, Module } from '@nestjs/common';
import { UniqueTenantAuthFactory } from '../unique-auth';
import { ConfluenceTenantAuthFactory } from './confluence-tenant-auth.factory';
import { TenantRegistry } from './tenant-registry';

@Global()
@Module({
  providers: [ConfluenceTenantAuthFactory, UniqueTenantAuthFactory, TenantRegistry],
  exports: [TenantRegistry],
})
export class TenantModule {}
