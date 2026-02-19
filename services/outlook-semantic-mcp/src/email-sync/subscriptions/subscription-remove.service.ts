import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/db';
import { traceAttrs, traceEvent } from '~/email-sync/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { SubscriptionRemovedEventDto } from './subscription.dtos';

export interface RemoveResult {
  status: 'removed' | 'not_found';
  subscription: {
    id: string;
    subscriptionId: string;
    expiresAt: Date;
    userProfileId: string;
    createdAt: Date;
    updatedAt: Date;
  } | null;
}

@Injectable()
export class SubscriptionRemoveService {
  private readonly logger = new Logger(SubscriptionRemoveService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
  ) {}

  @Span()
  public async enqueueSubscriptionRemoved(subscriptionId: string): Promise<void> {
    traceAttrs({
      subscription_id: subscriptionId,
      operation: 'enqueue_removal',
    });

    this.logger.debug({ subscriptionId }, 'Enqueuing subscription removal event for processing');

    const payload = await SubscriptionRemovedEventDto.encodeAsync({
      subscriptionId,
      type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-removed',
    });

    const published = await this.amqp.publish(MAIN_EXCHANGE.name, payload.type, payload, {});

    traceAttrs({ published });
    traceEvent('event published to AMQP', {
      exchangeName: MAIN_EXCHANGE.name,
      eventType: payload.type,
      published,
    });

    this.logger.debug(
      {
        exchangeName: MAIN_EXCHANGE.name,
        payload,
        published,
      },
      'Publishing event to message queue for asynchronous processing',
    );

    assert.ok(published, `Cannot publish AMQP event "${payload.type}"`);
  }

  @Span()
  public async removeByUserProfileId(userProfileId: UserProfileTypeID): Promise<RemoveResult> {
    traceAttrs({
      user_profile_id: userProfileId.toString(),
      operation: 'remove_subscription_by_user',
    });

    const existingSubscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'mail_monitoring'),
        eq(subscriptions.userProfileId, userProfileId.toString()),
      ),
    });

    if (!existingSubscription) {
      traceEvent('no subscription found for user');
      this.logger.debug({ userProfileId }, 'No active subscription found for user');
      return { status: 'not_found', subscription: null };
    }

    return this.remove(existingSubscription.subscriptionId);
  }

  @Span()
  public async remove(subscriptionId: string): Promise<RemoveResult> {
    traceAttrs({
      subscription_id: subscriptionId,
      operation: 'remove_subscription',
    });

    this.logger.log({ subscriptionId }, 'Beginning Microsoft Graph subscription removal process');

    const deletedSubscriptions = await this.db
      .delete(subscriptions)
      .where(and(eq(subscriptions.subscriptionId, subscriptionId)))
      .returning();

    traceEvent('deleted managed subscription', {
      subscriptionId,
      count: deletedSubscriptions.length,
    });

    this.logger.log(
      { subscriptionId, count: deletedSubscriptions.length },
      'Successfully deleted managed subscription record from database',
    );

    const deletedSubscription = deletedSubscriptions.at(0);
    if (!deletedSubscription) {
      traceEvent('no subscription found to delete');
      this.logger.debug({ subscriptionId }, 'No matching subscription found in database to delete');
      return { status: 'not_found', subscription: null };
    }

    traceAttrs({ user_profile_id: deletedSubscription.userProfileId });
    this.logger.debug(
      { subscriptionId, userProfileId: deletedSubscription.userProfileId },
      'Sending deletion request to Microsoft Graph API for subscription',
    );

    // NOTE: even if this deletion fails, whenever we get notification from microsoft we verify
    // the subscription exists on our DB as the source of truth, ignoring anything coming if not there
    // - so this is safe to do
    const client = this.graphClientFactory.createClientForUser(deletedSubscription.userProfileId);
    // Be explicit that this returns the response but we don't care about it if successful
    const _graphResponse = (await client
      .api(`/subscriptions/${subscriptionId}`)
      .header('Prefer', 'IdType="ImmutableId"')
      .delete()) as unknown;

    traceEvent('Graph API subscription deleted');
    this.logger.log(
      { subscriptionId },
      'Successfully removed subscription from Microsoft Graph API',
    );

    return { status: 'removed', subscription: deletedSubscription };
  }
}
