import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { GraphApiService } from './graph-api.service';
import { GraphAuthenticationProvider } from './graph-authentication.service';
import { GraphClientFactory } from './graph-client.factory';

@Module({
  imports: [ConfigModule],
  providers: [GraphAuthenticationProvider, GraphClientFactory, GraphApiService],
  exports: [GraphAuthenticationProvider, GraphClientFactory, GraphApiService],
})
export class MsGraphModule {}
