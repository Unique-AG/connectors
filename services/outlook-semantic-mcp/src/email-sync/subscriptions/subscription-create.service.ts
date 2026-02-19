import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span } from 'nestjs-otel';
import { DRIZZLE, type DrizzleDatabase, subscriptions, userProfiles } from '~/drizzle';
import { traceAttrs, traceEvent } from '~/email-sync/tracing.utils';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UserProfileTypeID } from '~/utils/convert-user-profile-id-to-type-id';
import { MAIN_EXCHANGE } from '../../amqp/amqp.constants';
import { subscriptionMailFilters } from '../mail-ingestion/dtos/subscription-mail-filters.dto';
import {
  CreateSubscriptionRequestSchema,
  LifecycleEventDto,
  Subscription,
} from './subscription.dtos';
import { MailSubscriptionUtilsService } from './subscription-utils.service';

export interface SubscribeResult {
  status: 'created' | 'already_active' | 'expiring_soon';
  subscription: {
    id: string;
    subscriptionId: string;
    expiresAt: Date;
    userProfileId: string;
    createdAt: Date;
    updatedAt: Date;
  };
}

@Injectable()
export class SubscriptionCreateService {
  private readonly logger = new Logger(SubscriptionCreateService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly utils: MailSubscriptionUtilsService,
  ) {}

  @Span()
  public async subscribe(
    userProfileId: UserProfileTypeID,
    filters: { dateFrom: string },
  ): Promise<SubscribeResult> {
    traceAttrs({
      user_profile_id: userProfileId.toString(),
      operation: 'create_subscription',
    });

    this.logger.log(
      { userProfileId: userProfileId.toString() },
      'Starting Microsoft Graph subscription creation process for user',
    );

    const existingSubscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'mail_monitoring'),
        eq(subscriptions.userProfileId, userProfileId.toString()),
      ),
    });

    if (existingSubscription) {
      traceEvent('found managed subscription', {
        id: existingSubscription.id,
      });
      this.logger.debug(
        { id: existingSubscription.id },
        'Located existing managed subscription in database',
      );

      const expiresAt = new Date(existingSubscription.expiresAt);
      const now = new Date();
      const diffFromNow = expiresAt.getTime() - now.getTime();

      traceAttrs({
        'subscription.expiresAt': expiresAt.toISOString(),
        'subscription.diffFromNowMs': diffFromNow,
      });

      this.logger.debug(
        { id: existingSubscription.id, expiresAt, now: now, diffFromNow },
        'Evaluating managed subscription expiration status',
      );

      // NOTE: 15 minutes is the last possible time we can get lifecycle notifications from Microsoft Graph
      // beyond that, we risk missing the notification and thus missing the chance to renew the subscription
      // automatically. In practice, we should aim to renew well before that to avoid any risk of missing it.
      // This threshold gives marks that last point to understand whether we should force a new subscription
      // or just keep it as is.
      const minimalTimeForLifecycleNotificationsInMinutes = 15;
      if (diffFromNow < 0) {
        traceEvent('subscription expired, deleting');

        const result = await this.db
          .delete(subscriptions)
          .where(eq(subscriptions.id, existingSubscription.id));

        traceEvent('expired managed subscription deleted', {
          id: existingSubscription.id,
          count: result.rowCount ?? NaN,
        });

        this.logger.log(
          { id: existingSubscription.id, count: result.rowCount ?? NaN },
          'Successfully deleted expired managed subscription from database',
        );
        return await this.createNewSubscription({
          userProfileId: userProfileId.toString(),
          filters,
        });
      }

      if (diffFromNow <= minimalTimeForLifecycleNotificationsInMinutes * 60 * 1000) {
        // NOTE: here we are below the threshold and ideally we should also be discarding the existing subscription
        // but there might be an edge case where this event gets picked up while a renewal is already in progress or
        // is about to happen very soon - this is a very unlikely edge case (never happened in prod),
        // but to be safe we just skip creating a new subscription here and let it naturally renew later or eventually expire.
        traceEvent('subscription expiration below renewal threshold', {
          id: existingSubscription.id,
          thresholdMinutes: minimalTimeForLifecycleNotificationsInMinutes,
        });

        this.logger.warn(
          {
            id: existingSubscription.id,
            thresholdMinutes: minimalTimeForLifecycleNotificationsInMinutes,
          },
          'Subscription expires too soon to renew safely, returning existing',
        );
        return { status: 'expiring_soon', subscription: existingSubscription };
      }

      // NOTE: here we have enough time left on the subscription, so we do nothing
      traceEvent('subscription valid, skipping creation');

      this.logger.debug(
        { id: existingSubscription.id },
        'Existing subscription is valid, skipping new subscription creation',
      );
      return { status: 'already_active', subscription: existingSubscription };
    }
    traceEvent('no existing subscription found');
    return await this.createNewSubscription({
      userProfileId: userProfileId.toString(),
      filters,
    });
  }

  private async createNewSubscription({
    userProfileId,
    filters,
  }: {
    userProfileId: string;
    filters: { dateFrom: string };
  }): Promise<SubscribeResult> {
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
      traceEvent('user profile not found');
      this.logger.error(
        { userProfileId: userProfileId.toString() },
        'Cannot proceed: user profile does not exist in database',
      );
      assert.fail(`${userProfileId} could not be found on DB`);
    }

    traceAttrs({
      'user_profile.provider_user_id': userProfile.providerUserId,
    });
    this.logger.debug(
      { providerUserId: userProfile.providerUserId },
      'Successfully retrieved user profile from database',
    );

    const payload = await CreateSubscriptionRequestSchema.encodeAsync({
      changeType: ['created'],
      notificationUrl,
      lifecycleNotificationUrl,
      clientState: webhookSecret,
      resource: `users/${userProfile.providerUserId}/messages`,
      expirationDateTime: nextScheduledExpiration,
    });

    traceEvent('new subscription payload prepared', {
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
    const graphResponse = (await client
      .api('/subscriptions')
      .header('Prefer', 'IdType="ImmutableId"')
      .post(payload)) as unknown;
    const graphSubscription = await Subscription.parseAsync(graphResponse);

    traceAttrs({ 'graph_subscription.id': graphSubscription.id });
    traceEvent('Graph API subscription created', {
      subscriptionId: graphSubscription.id,
    });

    this.logger.log(
      { subscriptionId: graphSubscription.id },
      'Microsoft Graph API subscription was created successfully',
    );

    const newManagedSubscriptions = await this.db
      .insert(subscriptions)
      .values({
        internalType: 'mail_monitoring',
        expiresAt: graphSubscription.expirationDateTime,
        userProfileId: userProfileId.toString(),
        subscriptionId: graphSubscription.id,
        filters: subscriptionMailFilters.encode({
          dateFrom: new Date(filters.dateFrom),
        }),
      })
      .returning();

    const created = newManagedSubscriptions.at(0);
    if (!created) {
      traceEvent('failed to create managed subscription in DB');
      assert.fail('subscription was not created');
    }

    traceEvent('new managed subscription created', { id: created.id });
    this.logger.log({ id: created.id }, 'Successfully created new managed subscription record');

    const subscriptionCreated = LifecycleEventDto.encode({
      type: 'unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-created',
      subscriptionId: created.subscriptionId,
    });
    await this.amqp.publish(MAIN_EXCHANGE.name, subscriptionCreated.type, subscriptionCreated);
    return { status: 'created', subscription: created };
  }
}
