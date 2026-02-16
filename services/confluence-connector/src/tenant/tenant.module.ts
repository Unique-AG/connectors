import { Global, Module } from '@nestjs/common';
import { ConfluenceTenantAuthFactory } from './confluence-tenant-auth.factory';
import { TenantRegistry } from './tenant-registry';

@Global()
@Module({
  providers: [ConfluenceTenantAuthFactory, TenantRegistry],
  exports: [TenantRegistry],
})
export class TenantModule {}
