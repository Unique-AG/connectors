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
    span?.setAttribute('subscriptionId', subscriptionId);

    this.logger.debug({ subscriptionId }, 'enqueuing subscription removed event');

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

    this.logger.log(
      {
        exchangeName: MAIN_EXCHANGE.name,
        payload,
        published,
      },
      `publishing "${payload.type}" event to AMQP exchange`,
    );

    if (!published) throw new Error(`Cannot publish AMQP event "${payload.type}"`);
  }

  @Span()
  public async remove(subscriptionId: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscriptionId', subscriptionId);

    this.logger.debug({ subscriptionId }, 'starting subscription removal');

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
      'deleted managed subscription',
    );

    const deletedSubscription = deletedSubscriptions.at(0);
    if (!deletedSubscription) {
      span?.addEvent('no subscription found to delete');
      this.logger.debug({ subscriptionId }, 'no subscription found to delete');
      return;
    }

    span?.setAttribute('userProfileId', deletedSubscription.userProfileId);
    this.logger.debug(
      { subscriptionId, userProfileId: deletedSubscription.userProfileId },
      'deleting subscription from Graph API',
    );

    const client = this.graphClientFactory.createClientForUser(deletedSubscription.userProfileId);
    const _graphResponse = (await client
      .api(`/subscriptions/${subscriptionId}`)
      .delete()) as unknown;

    span?.addEvent('Graph API subscription deleted');
    this.logger.log({ subscriptionId }, 'subscription removed from Graph API');
  }
}
