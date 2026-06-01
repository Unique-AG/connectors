import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/db/drizzle.module';
import { MsGraphModule } from '~/msgraph/msgraph.module';
import { GetMailboxTimezoneQuery } from './get-mailbox-timezone.query';
import { GetSubscriptionAndUserProfileQuery } from './get-subscription-and-user-profile.query';
import { GetUserProfileQuery } from './get-user-profile.query';

@Module({
  imports: [DrizzleModule, MsGraphModule],
  providers: [GetSubscriptionAndUserProfileQuery, GetUserProfileQuery, GetMailboxTimezoneQuery],
  exports: [GetSubscriptionAndUserProfileQuery, GetUserProfileQuery, GetMailboxTimezoneQuery],
})
export class UserUtilsModule {}
