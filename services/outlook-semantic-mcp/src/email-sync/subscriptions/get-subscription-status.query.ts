import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { DRIZZLE, DrizzleDatabase, subscriptions } from '~/db';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';

export type SubscriptionStatus =
  | 'subscription_missing' // Subscription does not exist
  | 'subscription_expired' // Subscription exists but is expired
  | 'subscription_connected'; // Subscription is connected and working

export type CheckSubscriptionQueryOutput =
  | {
      success: false;
      status: 'subscription_missing' | 'subscription_expired';
      message: string;
    }
  | {
      success: true;
      status: 'subscription_connected';
      message: string;
    };

@Injectable()
export class GetSubscriptionStatusQuery {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(@Inject(DRIZZLE) private readonly db: DrizzleDatabase) {}

  public async run(userProfileTypeID: UserProfileTypeID): Promise<CheckSubscriptionQueryOutput> {
    const subscriptionStatus = await this.getSubscriptionStatus(userProfileTypeID);
    this.logger.debug({
      userProfileId: userProfileTypeID.toString(),
      msg: subscriptionStatus.message,
      status: subscriptionStatus.success,
    });
    return subscriptionStatus;
  }

  private async getSubscriptionStatus(
    userProfileTypeID: UserProfileTypeID,
  ): Promise<CheckSubscriptionQueryOutput> {
    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'mail_monitoring'),
        eq(subscriptions.userProfileId, userProfileTypeID.toString()),
      ),
    });
    if (!subscription) {
      return {
        success: false,
        status: 'subscription_missing',
        message: 'Inbox is disconnected. Use connect_inbox to begin ingesting emails.',
      };
    }

    if (subscription.expiresAt < new Date()) {
      return {
        success: false,
        status: 'subscription_expired',
        message: 'Inbox is disconnected. Use connect_inbox to begin ingesting emails.',
      };
    }

    return {
      success: true,
      status: 'subscription_connected',
      message: 'Inbox connected, email sync running normally.',
    };
  }
}
