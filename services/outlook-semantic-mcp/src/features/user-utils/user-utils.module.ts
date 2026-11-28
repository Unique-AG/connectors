import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { CheckMailboxAccessQuery } from './check-mailbox-access.query';
import { GetMailboxTimezoneQuery } from './get-mailbox-timezone.query';
import { GetSubscriptionAndUserProfileQuery } from './get-subscription-and-user-profile.query';
import { GetUserProfileQuery } from './get-user-profile.query';
import { ResolveMailboxTimezoneQuery } from './resolve-mailbox-timezone.query';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [
    CheckMailboxAccessQuery,
    GetSubscriptionAndUserProfileQuery,
    GetUserProfileQuery,
    GetMailboxTimezoneQuery,
    ResolveMailboxTimezoneQuery,
  ],
  exports: [
    CheckMailboxAccessQuery,
    GetSubscriptionAndUserProfileQuery,
    GetUserProfileQuery,
    GetMailboxTimezoneQuery,
    ResolveMailboxTimezoneQuery,
  ],
})
export class UserUtilsModule {}
