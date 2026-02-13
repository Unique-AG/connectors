import { Module } from '@nestjs/common';
import { DrizzleModule } from '../../drizzle/drizzle.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { UniqueModule } from '../../unique/unique.module';
import { SubscriptionUtilsModule } from '../subscription-utils/subscription-utils.module';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { SyncDirectoriesCommand } from './sync-directories.command';
import { SyncDirectoriesWithDeltaCommand } from './sync-directories-with-delta.command';
import { SyncSystemDirectoriesCommand } from './sync-system-driectories.command';

const QUERIES = [FetchAllDirectoriesFromOutlookQuery];

const COMMANDS = [SyncDirectoriesCommand, SyncSystemDirectoriesCommand];
const PUBLIC_COMMANDS = [SyncDirectoriesWithDeltaCommand];

@Module({
  imports: [DrizzleModule, MsGraphModule, UniqueModule, SubscriptionUtilsModule],
  providers: [...QUERIES, ...COMMANDS, ...PUBLIC_COMMANDS],
  exports: [...QUERIES, ...COMMANDS, ...PUBLIC_COMMANDS],
})
export class DirectoriesSyncModule {}
