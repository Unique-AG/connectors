import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { UniqueApiFeatureModule } from '~/unique/unique-api.module';
import { InboxDeletingQueryModule } from '../delete-inbox/inbox-deleting-query.module';
import { UserUtilsModule } from '../user-utils/user-utils.module';
import { CreateRootScopeCommand } from './create-root-scope.command';
import { DirectorySyncSchedulerService } from './directories-sync-scheduler.service';
import { FetchAllDirectoriesFromOutlookQuery } from './fetch-all-directories-from-outlook.query';
import { RemoveRootScopeAndDirectoriesCommand } from './remove-root-scope-and-directories.command';
import { SyncDirectoriesCommand } from './sync-directories.command';
import { SyncDirectoriesForAllUserProfilesCommand } from './sync-directories-for-all-user-profiles.command';
import { SyncDirectoriesForUserProfileCommand } from './sync-directories-for-user-profile.command';
import { SyncSystemDirectoriesForSubscriptionCommand } from './sync-system-driectories-for-subscription.command';
import { UpsertDirectoryCommand } from './upsert-directory.command';

const QUERIES = [FetchAllDirectoriesFromOutlookQuery];

const COMMANDS = [
  SyncDirectoriesForUserProfileCommand,
  SyncSystemDirectoriesForSubscriptionCommand,
  SyncDirectoriesForAllUserProfilesCommand,
  CreateRootScopeCommand,
];
const PUBLIC_COMMANDS = [
  SyncDirectoriesCommand,
  RemoveRootScopeAndDirectoriesCommand,
  UpsertDirectoryCommand,
];

@Module({
  imports: [
    DrizzleModule,
    MsGraphModule,
    UserUtilsModule,
    UniqueApiFeatureModule,
    InboxDeletingQueryModule,
  ],
  providers: [...QUERIES, ...COMMANDS, ...PUBLIC_COMMANDS, DirectorySyncSchedulerService],
  exports: [...QUERIES, ...COMMANDS, ...PUBLIC_COMMANDS],
})
export class DirectoriesSyncModule {}
