import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { FileFilterService } from './file-filter.service';
import { GraphApiService } from './graph-api.service';
import { GraphAuthenticationProvider } from './graph-authentication.service';
import { GraphClientFactory } from './graph-client.factory';

@Module({
  imports: [ConfigModule],
  providers: [GraphAuthenticationProvider, GraphClientFactory, FileFilterService, GraphApiService],
  exports: [GraphAuthenticationProvider, GraphClientFactory, FileFilterService, GraphApiService],
})
export class MsGraphModule {}
