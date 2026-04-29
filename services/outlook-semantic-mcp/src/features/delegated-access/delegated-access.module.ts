import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { PersistentCacheModule } from '../persistent-cache/persistent-cache.module';
import { DiscoverDelegatedAccessCommand } from './discovery/discover-delegated-access.command';
import { DiscoverDelegatedAccessListener } from './discovery/discover-delegated-access.listener';
import { DiscoverDelegatedAccessSchedulerService } from './discovery/discover-delegated-access-scheduler.service';
import { SyncDelegatedAccessCommand } from './verification/sync-delegated-access.command';
import { SyncDelegatedAccessForAllUsersCommand } from './verification/sync-delegated-access-for-all-users.command';
import { VerifyDelegatedAccessListener } from './verification/verify-delegated-access.listener';
import { VerifyDelegatedAccessSchedulerService } from './verification/verify-delegated-access-scheduler.service';

@Module({
  imports: [DrizzleModule, MsGraphModule, PersistentCacheModule],
  providers: [
    // discovery
    DiscoverDelegatedAccessCommand,
    DiscoverDelegatedAccessListener,
    DiscoverDelegatedAccessSchedulerService,
    // verification
    SyncDelegatedAccessCommand,
    SyncDelegatedAccessForAllUsersCommand,
    VerifyDelegatedAccessListener,
    VerifyDelegatedAccessSchedulerService,
  ],
})
export class DelegatedAccessModule {}
