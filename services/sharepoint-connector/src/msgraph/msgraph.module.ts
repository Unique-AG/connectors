import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { GraphAuthenticationService } from './auth/graph-authentication.service';
import { FileFilterService } from './file-filter.service';
import { GraphApiService } from './graph-api.service';
import { GraphBatchService } from './graph-batch.service';
import { GraphClientFactory } from './graph-client.factory';

@Module({
  imports: [ConfigModule],
  providers: [
    GraphAuthenticationService,
    GraphClientFactory,
    FileFilterService,
    GraphBatchService,
    GraphApiService,
  ],
  exports: [
    GraphAuthenticationService,
    GraphClientFactory,
    FileFilterService,
    GraphBatchService,
    GraphApiService,
  ],
})
export class MsGraphModule {}
