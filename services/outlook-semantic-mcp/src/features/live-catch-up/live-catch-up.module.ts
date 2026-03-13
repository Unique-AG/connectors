import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { LiveCatchUpCommand } from './live-catch-up.command';
import { LiveCatchUpListener } from './live-catch-up.listener';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [LiveCatchUpCommand, LiveCatchUpListener],
  exports: [LiveCatchUpCommand],
})
export class LiveCatchUpModule {}
