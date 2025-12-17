import assert from 'node:assert';
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
    span?.setAttribute('user_profile_id', userProfileId.toString());

    const payload = await SubscriptionRequestedEventDto.encodeAsync({
      userProfileId,
      type: 'unique.teams-mcp.transcript.lifecycle-notification.subscription-requested',
    });

    this.logger.debug(
      { userProfileId: userProfileId.toString(), eventType: payload.type },
      'Enqueuing subscription request event for user profile processing',
    );

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
  public async subscribe(userProfileId: TypeID<'user_profile'>): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('user_profile_id', userProfileId.toString());

    this.logger.log(
      { userProfileId: userProfileId.toString() },
      'Starting Microsoft Graph subscription creation process for user',
    );

    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.userProfileId, userProfileId.toString()),
      ),
    });

    if (subscription) {
      span?.addEvent('found managed subscription', { id: subscription.id });
      this.logger.debug(
        { id: subscription.id },
        'Located existing managed subscription in database',
      );

      const expiresAt = new Date(subscription.expiresAt);
      const now = new Date();
      const diffFromNow = expiresAt.getTime() - now.getTime();

      span?.setAttribute('subscription.expiresAt', expiresAt.toISOString());
      span?.setAttribute('subscription.diffFromNowMs', diffFromNow);

      this.logger.debug(
        { id: subscription.id, expiresAt, now: now, diffFromNow },
        'Evaluating managed subscription expiration status',
      );

      const minimalTimeForLifecycleNotificationsInMinutes = 15;
      if (diffFromNow < 0) {
        span?.addEvent('subscription expired, deleting');

        const result = await this.db
          .delete(subscriptions)
          .where(eq(subscriptions.id, subscription.id));

        span?.addEvent('expired managed subscription deleted', {
          id: subscription.id,
          count: result.rowCount ?? NaN,
        });

        this.logger.log(
          { id: subscription.id, count: result.rowCount ?? NaN },
          'Successfully deleted expired managed subscription from database',
        );
      } else if (diffFromNow <= minimalTimeForLifecycleNotificationsInMinutes * 60 * 1000) {
        span?.addEvent('subscription below renewal threshold', {
          id: subscription.id,
          thresholdMinutes: minimalTimeForLifecycleNotificationsInMinutes,
        });

        this.logger.warn(
          { id: subscription.id, thresholdMinutes: minimalTimeForLifecycleNotificationsInMinutes },
          'Subscription expires too soon to renew safely, skipping creation',
        );
        return;
      } else {
        span?.addEvent('subscription valid, skipping creation');

        this.logger.debug(
          { id: subscription.id },
          'Existing subscription is valid, skipping new subscription creation',
        );
        return;
      }
    }

    span?.addEvent('no existing subscription found');
    this.logger.debug(
      {},
      'No existing subscription found, proceeding with new subscription creation',
    );

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
        'Cannot proceed: user profile does not exist in database',
      );
      throw new Error(`${userProfileId} could not be found on DB`);
    }

    span?.setAttribute('user_profile.provider_user_id', userProfile.providerUserId);
    this.logger.debug(
      { providerUserId: userProfile.providerUserId },
      'Successfully retrieved user profile from database',
    );

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

    this.logger.debug(
      {
        notificationUrl: payload.notificationUrl,
        lifecycleNotificationUrl: payload.lifecycleNotificationUrl,
        expirationDateTime: payload.expirationDateTime,
      },
      'Prepared Microsoft Graph subscription request payload',
    );

    this.logger.debug(
      { resource: payload.resource, changeType: payload.changeType },
      'Sending subscription creation request to Microsoft Graph API',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId.toString());
    const graphResponse = (await client.api('/subscriptions').post(payload)) as unknown;
    const graphSubscription = await Subscription.parseAsync(graphResponse);

    span?.setAttribute('graph_subscription.id', graphSubscription.id);
    span?.addEvent('Graph API subscription created', {
      subscriptionId: graphSubscription.id,
    });

    this.logger.log(
      { subscriptionId: graphSubscription.id },
      'Microsoft Graph API subscription was created successfully',
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
    this.logger.log({ id: created.id }, 'Successfully created new managed subscription record');
  }
}
