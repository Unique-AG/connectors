import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { DiscoverDelegatedAccessCommand } from './discovery/discover-delegated-access.command';
import { DiscoverDelegatedAccessListener } from './discovery/discover-delegated-access.listener';
import { DiscoverDelegatedAccessSchedulerService } from './discovery/discover-delegated-access-scheduler.service';
import { VerifyDelegatedAccessCommand } from './verification/verify-delegated-access.command';
import { VerifyDelegatedAccessListener } from './verification/verify-delegated-access.listener';
import { VerifyDelegatedAccessSchedulerService } from './verification/verify-delegated-access-scheduler.service';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [
    // discovery
    DiscoverDelegatedAccessCommand,
    DiscoverDelegatedAccessListener,
    DiscoverDelegatedAccessSchedulerService,
    // verification
    VerifyDelegatedAccessCommand,
    VerifyDelegatedAccessListener,
    VerifyDelegatedAccessSchedulerService,
  ],
})
export class DelegatedAccessModule {}
