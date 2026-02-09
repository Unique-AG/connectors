import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import {
  ReauthorizationRequiredEventDto,
  Subscription,
  UpdateSubscriptionRequestSchema,
} from './subscription.dtos';
import { MailSubscriptionUtilsService } from './subscription-utils.service';

@Injectable()
export class SubscriptionReauthorizeService {
  private readonly logger = new Logger(SubscriptionReauthorizeService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly utils: MailSubscriptionUtilsService,
  ) {}

  @Span()
  public async enqueueReauthorizationRequired(subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('operation', 'enqueue_reauthorization');

    this.logger.debug(
      { subscriptionId },
      'Enqueuing subscription reauthorization event for processing',
    );

    const payload = await ReauthorizationRequiredEventDto.encodeAsync({
      subscriptionId,
      type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.reauthorization-required',
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
  public async reauthorize(subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('operation', 'reauthorize_subscription');

    this.logger.log(
      { subscriptionId },
      'Beginning Microsoft Graph subscription reauthorization process',
    );

    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.subscriptionId, subscriptionId),
      ),
    });

    if (!subscription) {
      span?.addEvent('subscription not found for reauthorization');

      this.logger.warn(
        { subscriptionId },
        'Cannot reauthorize: subscription is not managed by this service',
      );
      return;
    }

    span?.setAttribute('user_profile_id', subscription.userProfileId);
    span?.setAttribute('subscription.id', subscription.id);

    this.logger.debug(
      { subscriptionId, managedId: subscription.id, userProfileId: subscription.userProfileId },
      'Located managed subscription record that requires reauthorization',
    );

    const nextScheduledExpiration = this.utils.getNextScheduledExpiration();

    const payload = await UpdateSubscriptionRequestSchema.encodeAsync({
      expirationDateTime: nextScheduledExpiration,
    });

    span?.addEvent('reauthorize subscription payload prepared', {
      expirationDateTime: payload.expirationDateTime,
    });

    this.logger.debug(
      {
        expirationDateTime: payload.expirationDateTime,
      },
      'Prepared Microsoft Graph subscription reauthorization request payload',
    );

    this.logger.debug(
      { subscriptionId, newExpiration: payload.expirationDateTime },
      'Sending reauthorization update request to Microsoft Graph API',
    );

    const client = this.graphClientFactory.createClientForUser(subscription.userProfileId);
    const graphResponse = (await client
      .api(`/subscriptions/${subscriptionId}`)
      .patch(payload)) as unknown;
    const graphSubscription = await Subscription.parseAsync(graphResponse);

    span?.addEvent('Graph API subscription updated', {
      newExpirationDateTime: graphSubscription.expirationDateTime.toISOString(),
    });

    this.logger.log(
      { subscriptionId, newExpiration: graphSubscription.expirationDateTime },
      'Microsoft Graph API subscription was successfully reauthorized',
    );

    const updates = await this.db
      .update(subscriptions)
      .set({
        expiresAt: graphSubscription.expirationDateTime,
      })
      .where(
        and(
          eq(subscriptions.internalType, 'transcript'),
          eq(subscriptions.subscriptionId, subscriptionId),
          eq(subscriptions.userProfileId, subscription.userProfileId),
        ),
      )
      .returning({ id: subscriptions.id });

    const updated = updates.at(0);
    if (!updated) {
      span?.addEvent('failed to update managed subscription in DB');
      assert.fail('subscription was not updated');
    }

    span?.addEvent('managed subscription updated', { id: updated.id });
    this.logger.log(
      { id: updated.id },
      'Successfully updated managed subscription record with new expiration',
    );
  }
}
