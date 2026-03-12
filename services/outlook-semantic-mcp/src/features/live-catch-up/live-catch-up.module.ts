import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { LiveCatchUpCommand } from './live-catch-up.command';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [LiveCatchUpCommand],
  exports: [LiveCatchUpCommand],
})
export class LiveCatchUpModule {}
