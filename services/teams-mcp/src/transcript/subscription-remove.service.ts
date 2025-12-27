import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { SubscriptionRemovedEventDto } from './transcript.dtos';

@Injectable()
export class SubscriptionRemoveService {
  private readonly logger = new Logger(SubscriptionRemoveService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
  ) {}

  @Span()
  public async enqueueSubscriptionRemoved(subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('operation', 'enqueue_removal');

    this.logger.debug({ subscriptionId }, 'Enqueuing subscription removal event for processing');

    const payload = await SubscriptionRemovedEventDto.encodeAsync({
      subscriptionId,
      type: 'unique.teams-mcp.transcript.lifecycle-notification.subscription-removed',
    });

    const published = await this.amqp.publish(MAIN_EXCHANGE.name, payload.type, payload, {});

    span?.setAttribute('published', published);
    span?.addEvent('event published to AMQP', {
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
  public async remove(subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('operation', 'remove_subscription');

    this.logger.log({ subscriptionId }, 'Beginning Microsoft Graph subscription removal process');

    const deletedSubscriptions = await this.db
      .delete(subscriptions)
      .where(and(eq(subscriptions.subscriptionId, subscriptionId)))
      .returning();

    span?.addEvent('deleted managed subscription', {
      subscriptionId,
      count: deletedSubscriptions.length,
    });

    this.logger.log(
      { subscriptionId, count: deletedSubscriptions.length },
      'Successfully deleted managed subscription record from database',
    );

    const deletedSubscription = deletedSubscriptions.at(0);
    if (!deletedSubscription) {
      span?.addEvent('no subscription found to delete');
      this.logger.debug({ subscriptionId }, 'No matching subscription found in database to delete');
      return;
    }

    span?.setAttribute('user_profile_id', deletedSubscription.userProfileId);
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
      .delete()) as unknown;

    span?.addEvent('Graph API subscription deleted');
    this.logger.log(
      { subscriptionId },
      'Successfully removed subscription from Microsoft Graph API',
    );
  }
}
