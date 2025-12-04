import { Subscription as MsGraphSubscription } from '@microsoft/microsoft-graph-types';
import {
  BeforeApplicationShutdown,
  Inject,
  Injectable,
  InternalServerErrorException,
  Logger,
} from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { EventEmitter2, OnEvent } from '@nestjs/event-emitter';
import { eq } from 'drizzle-orm';
import { serializeError } from 'serialize-error-cjs';
import { TypeID } from 'typeid-js';
import { AppEvents } from '../../app.events';
import { AppConfig, AppSettings } from '../../app-settings';
import { DRIZZLE, DrizzleDatabase, Folder, Subscription, subscriptions } from '../../drizzle';
import { GraphClientFactory } from '../../msgraph/graph-client.factory';
import { normalizeError } from '../../utils/normalize-error';
import {
  ChangeNotificationCollectionDto,
  ChangeNotificationDto,
} from './dto/change-notification-collection.dto';
import { SubscriptionEvent } from './subscription.events';

type SubscriptionResourceType = 'folder';
type SubscriptionResource = Folder;

@Injectable()
export class SubscriptionService implements BeforeApplicationShutdown {
  private readonly logger = new Logger(this.constructor.name);
  private readonly activeSubscriptions: Map<string, Subscription> = new Map();

  public constructor(
    private readonly configService: ConfigService<AppConfig, true>,
    private readonly graphClientFactory: GraphClientFactory,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly eventEmitter: EventEmitter2,
  ) {}

  @OnEvent(AppEvents.AppReady)
  public async onAppReady() {
    const subscriptionsList = await this.db.select().from(subscriptions);
    this.logger.log({
      msg: 'Creating subscriptions',
      count: subscriptionsList.length,
    });
    for (const subscription of subscriptionsList) {
      await this.startSubscription(subscription);
    }
  }

  // Cleanup via in-memory map, as other replicas of this service could hold other subscriptions.
  public async beforeApplicationShutdown() {
    this.logger.log({
      msg: 'Deleting subscriptions',
      count: this.activeSubscriptions.size,
    });
    for (const subscription of this.activeSubscriptions.values()) {
      await this.stopSubscription(subscription);
    }
  }

  /**
   * Create a subscription for a MS Graph resource synced to our service.
   *
   * Supported resources:
   * - folders
   *
   * @param userProfileId
   * @param resource
   */
  public async createSubscription(
    userProfileId: TypeID<'user_profile'>,
    resourceType: SubscriptionResourceType,
    resource: SubscriptionResource,
    { changeType = 'created,updated,deleted' }: { changeType?: 'created,updated,deleted' } = {},
  ) {
    const resourcePath = this.getMsGraphResource(resourceType, resource);

    try {
      const insertedSubscriptions = await this.db
        .insert(subscriptions)
        .values({
          resource: resourcePath,
          changeType,
          forId: resource.id,
          forType: resourceType,
          userProfileId: userProfileId.toString(),
        })
        .returning();
      const subscription = insertedSubscriptions[0];
      if (!subscription) throw new Error('Failed to insert subscription');

      await this.startSubscription(subscription);
    } catch (error) {
      this.logger.error({
        msg: 'Failed to create subscription',
        error: serializeError(normalizeError(error)),
      });
      throw new InternalServerErrorException(error);
    }
  }

  public async deleteSubscription(subscriptionId: TypeID<'subscription'>) {
    await this.stopSubscription(subscriptionId.toString());
    await this.db.delete(subscriptions).where(eq(subscriptions.id, subscriptionId.toString()));
  }

  public async onNotification(body: ChangeNotificationCollectionDto) {
    this.logger.log({
      msg: 'Subscription Webhook received',
    });
    if (!body.value) return;
    for (const notification of body.value) {
      if (!this.validateChangeNotification(notification)) {
        this.logger.warn({
          msg: 'Invalid MS Graph subscription webhook! Client state does not match.',
        });
        continue;
      }
      if (!notification.subscriptionId) {
        this.logger.debug('Notification has no subscriptionId');
        continue;
      }
      const subscription = await this.db.query.subscriptions.findFirst({
        where: eq(subscriptions.subscriptionId, notification.subscriptionId),
      });
      if (!subscription) {
        this.logger.warn({
          msg: 'Subscription not found',
          subscriptionId: notification.subscriptionId,
        });
        continue;
      }
      this.eventEmitter.emit(
        `subscription.notification.for.${subscription.forType}.${notification.changeType}`,
        new SubscriptionEvent(
          notification.subscriptionId,
          subscription.forId,
          notification.changeType as 'created' | 'updated' | 'deleted',
          notification.resourceData as {
            '@odata.type': string;
            '@odata.id': string;
            id: string;
          },
        ),
      );
    }
  }

  public async onLifecycle(body: ChangeNotificationCollectionDto) {
    this.logger.debug({
      msg: 'Lifecycle Webhook received',
      hasValue: !!body.value,
      valueCount: body.value?.length,
    });
    if (!body.value) return;
    for (const lifecycleEvent of body.value) {
      if (!this.validateChangeNotification(lifecycleEvent)) {
        this.logger.warn({
          msg: 'Invalid MS Graph lifecycle webhook! Client state does not match.',
        });
        continue;
      }
      if (!lifecycleEvent.lifecycleEvent) {
        this.logger.debug('Lifecycle event has no lifecycleEvent');
        continue;
      }
      if (!lifecycleEvent.subscriptionId) {
        this.logger.debug('Lifecycle event has no subscriptionId');
        continue;
      }

      switch (lifecycleEvent.lifecycleEvent) {
        case 'reauthorizationRequired':
          this.logger.log({
            msg: 'Lifecycle Update: Reauthorization required by Microsoft.',
            subscriptionId: lifecycleEvent.subscriptionId,
          });
          this.reauthorizeSubscription(lifecycleEvent.subscriptionId);
          break;
        case 'subscriptionRemoved':
          this.logger.log({
            msg: 'Lifecycle Update: Subscription removed by Microsoft.',
            subscriptionId: lifecycleEvent.subscriptionId,
          });
          this.stopSubscription(lifecycleEvent.subscriptionId);
          break;
        case 'missed':
          this.logger.debug({
            msg: 'Lifecycle Update: MS Graph subscription missed sending update.',
            subscriptionId: lifecycleEvent.subscriptionId,
          });
          break;
      }
    }
  }

  private async startSubscription(subscription: Subscription) {
    if (this.activeSubscriptions.has(subscription.id)) {
      this.logger.warn({
        msg: 'Subscription already exists',
        id: subscription.id,
        msGraphId: subscription.subscriptionId,
      });
      return;
    }

    const expirationTime = this.getMsGraphExpirationTime(subscription.forType);
    try {
      const msGraphSubscription: MsGraphSubscription = await this.createMsGraphSubscription(
        TypeID.fromString(subscription.userProfileId, 'user_profile'),
        subscription.changeType as 'created,updated,deleted',
        expirationTime,
        subscription.resource,
      );
      await this.db
        .update(subscriptions)
        .set({
          subscriptionId: msGraphSubscription.id,
          expiresAt: msGraphSubscription.expirationDateTime,
        })
        .where(eq(subscriptions.id, subscription.id));

      this.activeSubscriptions.set(subscription.id, subscription);

      this.logger.log({
        msg: 'Subscription created',
        id: subscription.id,
        msGraphId: msGraphSubscription.id,
        resource: subscription.resource,
        expirationTime: msGraphSubscription.expirationDateTime,
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed to create subscription. Deleting the subscription from the database.',
        error: serializeError(normalizeError(error)),
      });
      await this.deleteSubscription(TypeID.fromString(subscription.id, 'subscription'));
      throw new InternalServerErrorException(error);
    }
  }

  private async reauthorizeSubscription(msGraphSubscriptionId: string) {
    try {
      const subscription = await this.db.query.subscriptions.findFirst({
        where: eq(subscriptions.subscriptionId, msGraphSubscriptionId),
      });
      if (!subscription) throw new Error('Subscription not found');
      const client = this.graphClientFactory.createClientForUser(
        TypeID.fromString(subscription.userProfileId, 'user_profile'),
      );
      const newExpirationTime = this.getMsGraphExpirationTime(subscription.forType);
      await client.api(`/subscriptions/${msGraphSubscriptionId}`).patch({
        expirationDateTime: newExpirationTime,
      });
      await this.db
        .update(subscriptions)
        .set({
          expiresAt: newExpirationTime,
        })
        .where(eq(subscriptions.id, subscription.id));

      this.logger.log({
        msg: 'Subscription reauthorized',
        id: subscription.id,
        msGraphId: subscription.subscriptionId,
        newExpirationTime,
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed to reauthorize subscription.',
        error: serializeError(normalizeError(error)),
      });
    }
  }

  private async stopSubscription(subscription: Subscription | string) {
    let subscriptionToStop: Subscription;

    try {
      if (typeof subscription === 'string') {
        const foundSubscription = await this.db.query.subscriptions.findFirst({
          where: eq(subscriptions.subscriptionId, subscription),
        });
        if (!foundSubscription) return;
        subscriptionToStop = foundSubscription;
      } else {
        subscriptionToStop = subscription;
      }

      if (!subscriptionToStop.subscriptionId)
        throw new Error('This subscription does not have a MS Graph ID and seems to be inactive');
      await this.deleteMsGraphSubscription(subscriptionToStop.subscriptionId);
      if (!this.activeSubscriptions.has(subscriptionToStop.id)) {
        this.logger.warn({
          msg: 'Subscription is not active',
          id: subscriptionToStop.id,
          msGraphId: subscriptionToStop.subscriptionId,
        });
        return;
      }

      await this.db
        .update(subscriptions)
        .set({
          subscriptionId: null,
          expiresAt: null,
        })
        .where(eq(subscriptions.id, subscriptionToStop.id));

      this.activeSubscriptions.delete(subscriptionToStop.id);

      this.logger.log({
        msg: 'Subscription deleted',
        id: subscriptionToStop.id,
        msGraphId: subscriptionToStop.subscriptionId,
        resource: subscriptionToStop.resource,
      });
    } catch (error) {
      this.logger.error({
        msg: 'Failed to delete and stop subscription.',
        error: serializeError(normalizeError(error)),
      });
    }
  }

  private async createMsGraphSubscription(
    userProfileId: TypeID<'user_profile'>,
    changeType: 'created,updated,deleted',
    expirationTime: string,
    resourcePath: string,
  ) {
    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const payload: MsGraphSubscription = {
      changeType,
      clientState: this.configService.get(AppSettings.MICROSOFT_WEBHOOK_SECRET),
      expirationDateTime: expirationTime,
      includeResourceData: false,
      lifecycleNotificationUrl: `${this.configService.get(AppSettings.PUBLIC_WEBHOOK_URL)}/subscriptions/lifecycle`,
      notificationUrl: `${this.configService.get(AppSettings.PUBLIC_WEBHOOK_URL)}/subscriptions/notification`,
      resource: resourcePath,
    };
    return client.api('/subscriptions').post(payload);
  }

  private async deleteMsGraphSubscription(subscriptionId: string) {
    const client = this.graphClientFactory.createClientForUser(
      TypeID.fromString(subscriptionId, 'user_profile'),
    );
    await client.api(`/subscriptions/${subscriptionId}`).delete();
  }

  private getMsGraphExpirationTime(resourceType: SubscriptionResourceType) {
    switch (resourceType) {
      case 'folder':
        // return new Date(Date.now() + 1000 * 60 * 10070).toISOString(); // Little bit less than 7 days
        return new Date(Date.now() + 1000 * 60).toISOString(); // 1 minute
    }
  }

  private getMsGraphResource(
    resourceType: SubscriptionResourceType,
    resource: SubscriptionResource,
  ) {
    switch (resourceType) {
      case 'folder':
        return `/me/mailFolders('${resource.folderId}')/messages`;
    }
  }

  private validateChangeNotification(notification: ChangeNotificationDto): boolean {
    return (
      notification.clientState === this.configService.get(AppSettings.MICROSOFT_WEBHOOK_SECRET)
    );
  }
}
