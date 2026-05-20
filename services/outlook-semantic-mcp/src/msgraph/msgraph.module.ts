import { Module } from '@nestjs/common';
import { DrizzleModule } from '../db/drizzle.module';
import { GraphClientFactory } from './graph-client.factory';
import { MsGraphClientResolver } from './ms-graph-client-resolver.service';

@Module({
  imports: [DrizzleModule],
  providers: [GraphClientFactory, MsGraphClientResolver],
  exports: [GraphClientFactory, MsGraphClientResolver],
})
export class MsGraphModule {}
