import { Module } from '@nestjs/common';
import { DrizzleModule } from '~/drizzle/drizzle.module';
import { GetSubscriptionAndUserProfileQuery } from './get-subscription-and-user-profile.query';

@Module({
  imports: [DrizzleModule],
  providers: [GetSubscriptionAndUserProfileQuery],
  exports: [GetSubscriptionAndUserProfileQuery],
})
export class SubscriptionUtilsModule {}
