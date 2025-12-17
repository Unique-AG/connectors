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
} from './transcript.dtos';
import { TranscriptUtilsService } from './transcript-utils.service';

@Injectable()
export class SubscriptionReauthorizeService {
  private readonly logger = new Logger(SubscriptionReauthorizeService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly utils: TranscriptUtilsService,
  ) {}

  @Span()
  public async enqueueReauthorizationRequired(subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscriptionId', subscriptionId);

    this.logger.debug({ subscriptionId }, 'enqueuing reauthorization required event');

    const payload = await ReauthorizationRequiredEventDto.encodeAsync({
      subscriptionId,
      type: 'unique.teams-mcp.transcript.lifecycle-notification.reauthorization-required',
    });

    const published = await this.amqp.publish(MAIN_EXCHANGE.name, payload.type, payload, {});

    span?.setAttribute('published', published);
    span?.addEvent('event published to AMQP', {
      exchangeName: MAIN_EXCHANGE.name,
      eventType: payload.type,
      published,
    });

    this.logger.log(
      {
        exchangeName: MAIN_EXCHANGE.name,
        payload,
        published,
      },
      `publishing "${payload.type}" event to AMQP exchange`,
    );

    assert.ok(published, `Cannot publish AMQP event "${payload.type}"`);
  }

  @Span()
  public async reauthorize(subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscriptionId', subscriptionId);

    this.logger.debug({ subscriptionId }, 'starting subscription reauthorization');

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
        "the requested reauthorization is for a subscription we don't manage",
      );
      return;
    }

    span?.setAttribute('userProfileId', subscription.userProfileId);
    span?.setAttribute('subscription.id', subscription.id);

    this.logger.debug(
      { subscriptionId, managedId: subscription.id, userProfileId: subscription.userProfileId },
      'found managed subscription for reauthorization',
    );

    const nextScheduledExpiration = this.utils.getNextScheduledExpiration();

    const payload = await UpdateSubscriptionRequestSchema.encodeAsync({
      expirationDateTime: nextScheduledExpiration,
    });

    span?.addEvent('reauthorize subscription payload prepared', {
      expirationDateTime: payload.expirationDateTime,
    });

    this.logger.log(
      {
        expirationDateTime: payload.expirationDateTime,
      },
      'reauthorize subscription payload prepared',
    );

    this.logger.debug(
      { subscriptionId, newExpiration: payload.expirationDateTime },
      'updating subscription in Graph API',
    );

    const client = this.graphClientFactory.createClientForUser(subscription.userProfileId);
    const graphResponse = (await client
      .api(`/subscriptions/${subscriptionId}`)
      .patch(payload)) as unknown;
    const graphSubscription = await Subscription.parseAsync(graphResponse);

    span?.addEvent('Graph API subscription updated', {
      newExpirationDateTime: graphSubscription.expirationDateTime.toISOString(),
    });

    this.logger.debug(
      { subscriptionId, newExpiration: graphSubscription.expirationDateTime },
      'Graph API subscription updated successfully',
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
      throw new Error('subscription was not updated');
    }

    span?.addEvent('managed subscription updated', { id: updated.id });
    this.logger.log({ id: updated.id }, 'managed subscription updated');
  }
}
