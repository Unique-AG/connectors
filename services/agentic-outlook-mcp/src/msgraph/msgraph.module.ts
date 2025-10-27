import { Module } from '@nestjs/common';
import { DrizzleModule } from '../drizzle/drizzle.module';
import { GraphClientFactory } from './graph-client.factory';

@Module({
  imports: [DrizzleModule],
  providers: [GraphClientFactory],
  exports: [GraphClientFactory],
})
export class MsGraphModule {}
