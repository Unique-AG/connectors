import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { SubscriptionUtilsModule } from '../user-utils/subscription-utils.module';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { DirectorySyncSchedulerService } from './directories-sync-scheduler.service';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { SyncDirectoriesCommand } from './sync-directories.command';
import { SyncDirectoriesForSubscriptionCommand } from './sync-directories-for-subscription.command';
import { SyncDirectoriesForSubscriptionsCommand } from './sync-directories-for-subscriptions.command';
import { SyncSystemDirectoriesForSubscriptionCommand } from './sync-system-driectories-for-subscription.command';
import { RunDirectorySyncTool } from './tools/run-directory-sync.tool';

const QUERIES = [FetchAllDirectoriesFromOutlookQuery];

const COMMANDS = [
  SyncDirectoriesForSubscriptionCommand,
  SyncSystemDirectoriesForSubscriptionCommand,
  SyncDirectoriesForSubscriptionsCommand,
  CreateRootScopeCommand,
];
const PUBLIC_COMMANDS = [SyncDirectoriesCommand];

@Module({
  imports: [DrizzleModule, MsGraphModule, SubscriptionUtilsModule, UniqueApiFeatureModule],
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
