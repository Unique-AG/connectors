import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { MicrosoftAuthenticationService } from './auth/microsoft-authentication.service';
import { FileFilterService } from './graph/file-filter.service';
import { GraphApiService } from './graph/graph-api.service';
import { GraphClientFactory } from './graph/graph-client.factory';

@Module({
  imports: [ConfigModule],
  providers: [
    MicrosoftAuthenticationService,
    GraphClientFactory,
    FileFilterService,
    GraphApiService,
  ],
  exports: [MicrosoftAuthenticationService, GraphClientFactory, GraphApiService],
})
export class MicrosoftApisModule {}
