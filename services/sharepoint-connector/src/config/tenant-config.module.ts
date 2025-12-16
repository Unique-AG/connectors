import { Module } from '@nestjs/common';
import { MicrosoftApisModule } from '../microsoft-apis/microsoft-apis.module';
import { TenantConfigLoaderService } from './tenant-config-loader.service';

@Module({
  imports: [MicrosoftApisModule],
  providers: [TenantConfigLoaderService],
  exports: [TenantConfigLoaderService],
})
export class TenantConfigModule {}
