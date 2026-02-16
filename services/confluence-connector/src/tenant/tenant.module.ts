import { Global, Module } from '@nestjs/common';
import { TenantAuthFactory } from './tenant-auth.factory';
import { TenantRegistry } from './tenant-registry';

@Global()
@Module({
  providers: [TenantAuthFactory, TenantRegistry],
  exports: [TenantRegistry],
})
export class TenantModule {}
