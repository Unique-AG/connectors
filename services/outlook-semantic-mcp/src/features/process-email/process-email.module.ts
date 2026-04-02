import { Module, Provider } from '@nestjs/common';
import { ConfigModule } from '@nestjs/config';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { DirectoriesSyncModule } from '../directories-sync/directories-sync.module';
import { ProcessEmailCommand } from './process-email.command';

const COMMANDS: Provider[] = [ProcessEmailCommand];

@Module({
  imports: [
    ConfigModule,
    DrizzleModule,
    MsGraphModule,
    DirectoriesSyncModule,
    UniqueApiFeatureModule,
  ],
  providers: [...COMMANDS],
  exports: [...COMMANDS],
})
export class ProcessEmailModule {}
