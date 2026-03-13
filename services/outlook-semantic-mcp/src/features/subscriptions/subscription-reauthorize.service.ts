import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/db';
import { traceAttrs, traceEvent } from '~/features/tracing.utils';
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
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly utils: MailSubscriptionUtilsService,
  ) {}

  @Span()
  public async enqueueReauthorizationRequired(subscriptionId: string): Promise<void> {
    traceAttrs({
      subscriptionId: subscriptionId,
      operation: 'enqueue_reauthorization',
    });

    this.logger.debug({
      msg: 'Enqueuing subscription reauthorization event for processing',
      subscriptionId,
    });

    const payload = await ReauthorizationRequiredEventDto.encodeAsync({
      subscriptionId,
      type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.reauthorization-required',
    });

    const published = await this.amqp.publish(MAIN_EXCHANGE.name, payload.type, payload, {});

    traceAttrs({ published });
    traceEvent('event published to AMQP', {
      exchangeName: MAIN_EXCHANGE.name,
      eventType: payload.type,
      published,
    });

    this.logger.debug({
      msg: 'Publishing event to message queue for asynchronous processing',
      exchangeName: MAIN_EXCHANGE.name,
      payload,
      published,
    });

    assert.ok(published, `Cannot publish AMQP event "${payload.type}"`);
  }

  @Span()
  public async reauthorize(subscriptionId: string): Promise<void> {
    traceAttrs({
      subscriptionId: subscriptionId,
      operation: 'reauthorize_subscription',
    });

    this.logger.log({
      msg: 'Beginning Microsoft Graph subscription reauthorization process',
      subscriptionId,
    });

    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'mail_monitoring'),
        eq(subscriptions.subscriptionId, subscriptionId),
      ),
    });

    if (!subscription) {
      traceEvent('subscription not found for reauthorization');

      this.logger.warn({
        msg: 'Cannot reauthorize: subscription is not managed by this service',
        subscriptionId,
      });
      return;
    }

    traceAttrs({
      userProfileId: subscription.userProfileId,
      'subscription.id': subscription.id,
    });

    this.logger.debug({
      msg: 'Located managed subscription record that requires reauthorization',
      subscriptionId,
      managedId: subscription.id,
      userProfileId: subscription.userProfileId,
    });

    const nextScheduledExpiration = this.utils.getNextScheduledExpiration();

    const payload = await UpdateSubscriptionRequestSchema.encodeAsync({
      expirationDateTime: nextScheduledExpiration,
    });

    traceEvent('reauthorize subscription payload prepared', {
      expirationDateTime: payload.expirationDateTime,
    });

    this.logger.debug({
      msg: 'Prepared Microsoft Graph subscription reauthorization request payload',
      expirationDateTime: payload.expirationDateTime,
    });

    this.logger.debug({
      msg: 'Sending reauthorization update request to Microsoft Graph API',
      subscriptionId,
      newExpiration: payload.expirationDateTime,
    });

    const client = this.graphClientFactory.createClientForUser(subscription.userProfileId);
    const graphResponse = (await client
      .api(`/subscriptions/${subscriptionId}`)
      .header('Prefer', 'IdType="ImmutableId"')
      .patch(payload)) as unknown;
    const graphSubscription = await Subscription.parseAsync(graphResponse);

    traceEvent('Graph API subscription updated', {
      newExpirationDateTime: graphSubscription.expirationDateTime.toISOString(),
    });

    this.logger.log({
      msg: 'Microsoft Graph API subscription was successfully reauthorized',
      subscriptionId,
      newExpiration: graphSubscription.expirationDateTime,
    });

    const updates = await this.db
      .update(subscriptions)
      .set({
        expiresAt: graphSubscription.expirationDateTime,
      })
      .where(
        and(
          eq(subscriptions.internalType, 'mail_monitoring'),
          eq(subscriptions.subscriptionId, subscriptionId),
          eq(subscriptions.userProfileId, subscription.userProfileId),
        ),
      )
      .returning({ id: subscriptions.id });

    const updated = updates.at(0);
    if (!updated) {
      traceEvent('failed to update managed subscription in DB');
      assert.fail('subscription was not updated');
    }

    traceEvent('managed subscription updated', { id: updated.id });
    this.logger.log({
      msg: 'Successfully updated managed subscription record with new expiration',
      id: updated.id,
    });
  }
}
