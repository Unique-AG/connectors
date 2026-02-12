import assert from 'node:assert';
import { Inject, Injectable } from '@nestjs/common';
import { eq } from 'drizzle-orm';
import { TraceService } from 'nestjs-otel';
import {
  DRIZZLE,
  DrizzleDatabase,
  Subscription,
  subscriptions,
  UserProfile,
  userProfiles,
} from '~/drizzle';
import { NonNullishProps } from '../../utils/non-nullish-props';

@Injectable()
export class GetSubscriptionAndUserProfileQuery {
  public constructor(
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly trace: TraceService,
  ) {}

  public async run(subscriptionId: string): Promise<{
    subscription: Subscription;
    userProfile: NonNullishProps<UserProfile, 'email'>;
  }> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId.toString());
    const subscription = await this.db.query.subscriptions.findFirst({
      where: eq(subscriptions.subscriptionId, subscriptionId),
    });
    assert.ok(subscription, `Subscription missing for: ${subscriptionId}`);
    const userProfile = await this.db.query.userProfiles.findFirst({
      where: eq(userProfiles.id, subscription.userProfileId),
    });
    assert.ok(userProfile, `User Profile missing for: ${subscription.id}`);
    span?.setAttribute('user_profile_id', userProfile.id);
    const email = userProfile.email;
    assert.ok(email, `User Profile with id:${userProfile.id} has no email ${email}`);

    return { subscription, userProfile: { ...userProfile, email } };
  }
}
