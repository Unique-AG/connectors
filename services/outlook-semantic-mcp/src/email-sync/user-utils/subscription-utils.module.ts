import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { GetSubscriptionAndUserProfileQuery } from './get-subscription-and-user-profile.query';
import { GetUserProfileQuery } from './get-user-profile.query';

@Module({
  imports: [DrizzleModule],
  providers: [GetSubscriptionAndUserProfileQuery, GetUserProfileQuery],
  exports: [GetSubscriptionAndUserProfileQuery, GetUserProfileQuery],
})
export class SubscriptionUtilsModule {}
