import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { MsGraphModule } from '../../msgraph/msgraph.module';
import { SubscriptionUtilsModule } from '../user-utils/subscription-utils.module';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { DirectorySyncSchedulerService } from './directories-sync-scheduler.service';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { ListDirectoriesQuery } from './list-directories.query';
import { RemoveRootScopeAndDirectoriesCommand } from './remove-root-scope-and-directories.command';
import { SyncDirectoriesCommand } from './sync-directories.command';
import { SyncDirectoriesForSubscriptionsCommand } from './sync-directories-for-subscriptions.command';
import { SyncDirectoriesForUserProfileCommand } from './sync-directories-for-user-profile.command';
import { SyncSystemDirectoriesForSubscriptionCommand } from './sync-system-driectories-for-subscription.command';
import { UpsertDirectoryCommand } from './upsert-directory.command';

const QUERIES = [FetchAllDirectoriesFromOutlookQuery, ListDirectoriesQuery];

const COMMANDS = [
  SyncDirectoriesForUserProfileCommand,
  SyncSystemDirectoriesForSubscriptionCommand,
  SyncDirectoriesForSubscriptionsCommand,
  CreateRootScopeCommand,
];
const PUBLIC_COMMANDS = [
  SyncDirectoriesCommand,
  RemoveRootScopeAndDirectoriesCommand,
  UpsertDirectoryCommand,
];

@Module({
  imports: [DrizzleModule, MsGraphModule, SubscriptionUtilsModule, UniqueApiFeatureModule],
  providers: [...QUERIES, ...COMMANDS, ...PUBLIC_COMMANDS, DirectorySyncSchedulerService],
  exports: [...QUERIES, ...COMMANDS, ...PUBLIC_COMMANDS],
})
export class DirectoriesSyncModule {}
