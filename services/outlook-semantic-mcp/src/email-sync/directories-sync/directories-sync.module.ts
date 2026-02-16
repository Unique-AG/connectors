import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { UNIQUE_API_FEATURE_MODULE } from '~/unique/unique-api.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { SubscriptionUtilsModule } from '../subscription-utils/subscription-utils.module';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { DirectorySyncSchedulerService } from './directories-sync-scheduler.service';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { SyncDirectoriesCommand } from './sync-directories.command';
import { SyncDirectoriesForSubscriptionsCommand } from './sync-directories-for-subscriptions.command';
import { SyncDirectoriesWithDeltaCommand } from './sync-directories-with-delta.command';
import { SyncSystemDirectoriesCommand } from './sync-system-driectories.command';
import { RunDirectorySyncTool } from './tools/run-directory-sync.tool';

const QUERIES = [FetchAllDirectoriesFromOutlookQuery];

const COMMANDS = [
  SyncDirectoriesCommand,
  SyncSystemDirectoriesCommand,
  SyncDirectoriesForSubscriptionsCommand,
  CreateRootScopeCommand,
];
const PUBLIC_COMMANDS = [SyncDirectoriesWithDeltaCommand];

@Module({
  imports: [DrizzleModule, MsGraphModule, SubscriptionUtilsModule, UNIQUE_API_FEATURE_MODULE],
  providers: [
    ...QUERIES,
    ...COMMANDS,
    ...PUBLIC_COMMANDS,
    DirectorySyncSchedulerService,
    RunDirectorySyncTool,
  ],
  exports: [...QUERIES, ...COMMANDS, ...PUBLIC_COMMANDS],
})
export class DirectoriesSyncModule {}
