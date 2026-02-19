import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, Subscription, subscriptions, UserProfile } from '~/db';
import { traceAttrs } from '~/email-sync/tracing.utils';
import { convertUserProfileIdToTypeId } from '~/utils/convert-user-profile-id-to-type-id';
import { NonNullishProps } from '../../utils/non-nullish-props';
import { GetUserProfileQuery } from './get-user-profile.query';

@Injectable()
export class GetSubscriptionAndUserProfileQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly getUserProfileQuery: GetUserProfileQuery,
  ) {}

  public async run(subscriptionId: string): Promise<{
    subscription: Subscription;
    userProfile: NonNullishProps<UserProfile, 'email'>;
  }> {
    traceAttrs({ subscription_id: subscriptionId.toString() });
    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.subscriptionId, subscriptionId),
    });
    assert.ok(subscription, `Subscription missing for: ${subscriptionId}`);
    const userProfile = await this.getUserProfileQuery.run(
      convertUserProfileIdToTypeId(subscription.userProfileId),
    );

    return { subscription, userProfile };
  }
}
