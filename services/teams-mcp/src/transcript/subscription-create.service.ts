import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import type { TypeID } from 'typeid-js';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions, userProfiles } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import {
  CreateSubscriptionRequestSchema,
  Subscription,
  SubscriptionRequestedEventDto,
} from './transcript.dtos';
import { TranscriptUtilsService } from './transcript-utils.service';

@Injectable()
export class SubscriptionCreateService {
  private readonly logger = new Logger(SubscriptionCreateService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly utils: TranscriptUtilsService,
  ) {}

  @Span()
  public async enqueueSubscriptionRequested(userProfileId: TypeID<'user_profile'>): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('userProfileId', userProfileId.toString());

    const payload = await SubscriptionRequestedEventDto.encodeAsync({
      userProfileId,
      type: 'unique.teams-mcp.transcript.lifecycle-notification.subscription-requested',
    });

    this.logger.debug(
      { userProfileId: userProfileId.toString(), eventType: payload.type },
      'enqueuing subscription requested event',
    );

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
  public async subscribe(userProfileId: TypeID<'user_profile'>): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('userProfileId', userProfileId.toString());

    this.logger.debug({ userProfileId: userProfileId.toString() }, 'starting subscription process');

    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.userProfileId, userProfileId.toString()),
      ),
    });

    if (subscription) {
      span?.addEvent('found managed subscription', { id: subscription.id });
      this.logger.log({ id: subscription.id }, 'found managed subscription in DB');

      const expiresAt = new Date(subscription.expiresAt);
      const now = new Date();
      const diffFromNow = expiresAt.getTime() - now.getTime();

      span?.setAttribute('subscription.expiresAt', expiresAt.toISOString());
      span?.setAttribute('subscription.diffFromNowMs', diffFromNow);

      this.logger.debug(
        { id: subscription.id, expiresAt, now: now, diffFromNow },
        'managed subscription expiration',
      );

      const minimalTimeForLifecycleNotificationsInMinutes = 15;
      if (diffFromNow < 0) {
        span?.addEvent('subscription expired, deleting');

        const result = await this.db
          .delete(subscriptions)
          .where(eq(subscriptions.id, subscription.id));

        span?.addEvent('expired managed subscription yeeted', {
          id: subscription.id,
          count: result.rowCount ?? NaN,
        });

        this.logger.log(
          { id: subscription.id, count: result.rowCount ?? NaN },
          'expired managed subscription yeeted',
        );
      } else if (diffFromNow <= minimalTimeForLifecycleNotificationsInMinutes * 60 * 1000) {
        span?.addEvent('subscription below renewal threshold', {
          id: subscription.id,
          thresholdMinutes: minimalTimeForLifecycleNotificationsInMinutes,
        });

        this.logger.warn(
          { id: subscription.id },
          `subscription is below "${minimalTimeForLifecycleNotificationsInMinutes}" minutes threshold`,
        );
        return;
      } else {
        span?.addEvent('subscription valid, skipping creation');

        this.logger.log({ id: subscription.id }, 'skipping creation of new subscription');
        return;
      }
    }

    span?.addEvent('no existing subscription found');
    this.logger.debug('no existing subscription found, creating new one');

    const { notificationUrl, lifecycleNotificationUrl } = this.utils.getSubscriptionURLs();
    const nextScheduledExpiration = this.utils.getNextScheduledExpiration();
    const webhookSecret = this.utils.getWebhookSecret();

    const userProfile = await this.db.query.userProfiles.findFirst({
      columns: {
        providerUserId: true,
      },
      where: eq(userProfiles.id, userProfileId.toString()),
    });

    if (!userProfile) {
      span?.addEvent('user profile not found');
      this.logger.error(
        { userProfileId: userProfileId.toString() },
        'user profile not found in DB',
      );
      throw new Error(`${userProfileId} could not be found on DB`);
    }

    span?.setAttribute('userProfile.providerUserId', userProfile.providerUserId);
    this.logger.debug({ providerUserId: userProfile.providerUserId }, 'user profile retrieved');

    const payload = await CreateSubscriptionRequestSchema.encodeAsync({
      changeType: ['created'],
      notificationUrl,
      lifecycleNotificationUrl,
      clientState: webhookSecret,
      resource: `users/${userProfile.providerUserId}/onlineMeetings/getAllTranscripts`,
      expirationDateTime: nextScheduledExpiration,
    });

    span?.addEvent('new subscription payload prepared', {
      notificationUrl: payload.notificationUrl,
      lifecycleNotificationUrl: payload.lifecycleNotificationUrl,
      expirationDateTime: payload.expirationDateTime,
    });

    this.logger.log(
      {
        notificationUrl: payload.notificationUrl,
        lifecycleNotificationUrl: payload.lifecycleNotificationUrl,
        expirationDateTime: payload.expirationDateTime,
      },
      'new subscription payload prepared',
    );

    this.logger.debug(
      { resource: payload.resource, changeType: payload.changeType },
      'creating Graph API subscription',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId.toString());
    const graphResponse = (await client.api('/subscriptions').post(payload)) as unknown;
    const graphSubscription = await Subscription.parseAsync(graphResponse);

    span?.setAttribute('graphSubscription.id', graphSubscription.id);
    span?.addEvent('Graph API subscription created', {
      subscriptionId: graphSubscription.id,
    });

    this.logger.debug(
      { subscriptionId: graphSubscription.id },
      'Graph API subscription created successfully',
    );

    const newManagedSubscriptions = await this.db
      .insert(subscriptions)
      .values({
        internalType: 'transcript',
        expiresAt: graphSubscription.expirationDateTime,
        userProfileId: userProfileId.toString(),
        subscriptionId: graphSubscription.id,
      })
      .returning({ id: subscriptions.id });

    const created = newManagedSubscriptions.at(0);
    if (!created) {
      span?.addEvent('failed to create managed subscription in DB');
      throw new Error('subscription was not created');
    }

    span?.addEvent('new managed subscription created', { id: created.id });
    this.logger.log({ id: created.id }, 'new managed subscription created');
  }
}
