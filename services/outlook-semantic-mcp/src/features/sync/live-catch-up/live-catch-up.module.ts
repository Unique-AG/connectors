import { Module } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { DirectoriesSyncModule } from '~/features/directories-sync/directories-sync.module';
import { ProcessEmailModule } from '~/features/process-email/process-email.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { LiveCatchUpCommand } from './live-catch-up.command';
import { LiveCatchUpListener } from './live-catch-up.listener';

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    DirectoriesSyncModule,
    ProcessEmailModule,
    ConfigModule,
    UniqueApiFeatureModule,
  ],
  providers: [LiveCatchUpCommand, LiveCatchUpListener],
  exports: [LiveCatchUpCommand],
})
export class LiveCatchUpModule {}
