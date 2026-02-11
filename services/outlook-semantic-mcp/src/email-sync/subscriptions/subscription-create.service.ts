import assert from "node:assert";
import { AmqpConnection } from "@golevelup/nestjs-rabbitmq";
import { Inject, Injectable, Logger } from "@nestjs/common";
import { and, eq } from "drizzle-orm";
import { Span, TraceService } from "nestjs-otel";
import type { TypeID } from "typeid-js";
import { MAIN_EXCHANGE } from "~/amqp/amqp.constants";
import {
  DRIZZLE,
  type DrizzleDatabase,
  mailFoldersSync,
  subscriptions,
  userProfiles,
} from "~/drizzle";
import { GraphClientFactory } from "~/msgraph/graph-client.factory";
import {
  CreateSubscriptionRequestSchema,
  Subscription,
  SubscriptionRequestedEventDto,
} from "./subscription.dtos";
import { MailSubscriptionUtilsService } from "./subscription-utils.service";
import { FetchOrCreateOutlookEmailsRootScopeCommand } from "~/unique/unique-scopes/fetch-or-create-outlook-emails-root-scope.command";

export interface SubscribeResult {
  status: "created" | "already_active" | "expiring_soon";
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
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly utils: MailSubscriptionUtilsService,
    private readonly fetchOrCreateOutlookEmailsRootScopeCommand: FetchOrCreateOutlookEmailsRootScopeCommand,
  ) {}

  @Span()
  public async enqueueSubscriptionRequested(
    userProfileId: TypeID<"user_profile">,
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute("user_profile_id", userProfileId.toString());
    span?.setAttribute("operation", "enqueue_subscription_request");

    const payload = await SubscriptionRequestedEventDto.encodeAsync({
      userProfileId,
      type: "unique.outlook-semantic-mcp.mail.lifecycle-notification.subscription-requested",
    });

    this.logger.debug(
      { userProfileId: userProfileId.toString(), eventType: payload.type },
      "Enqueuing subscription request event for user profile processing",
    );

    const published = await this.amqp.publish(
      MAIN_EXCHANGE.name,
      payload.type,
      payload,
      {},
    );

    span?.setAttribute("published", published);
    span?.addEvent("event published to AMQP", {
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
      "Publishing event to message queue for asynchronous processing",
    );

    assert.ok(published, `Cannot publish AMQP event "${payload.type}"`);
  }

  @Span()
  public async subscribe(
    userProfileId: TypeID<"user_profile">,
  ): Promise<SubscribeResult> {
    const span = this.trace.getSpan();
    span?.setAttribute("user_profile_id", userProfileId.toString());
    span?.setAttribute("operation", "create_subscription");

    this.logger.log(
      { userProfileId: userProfileId.toString() },
      "Starting Microsoft Graph subscription creation process for user",
    );

    const existingSubscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, "mail_monitoring"),
        eq(subscriptions.userProfileId, userProfileId.toString()),
      ),
    });

    if (existingSubscription) {
      span?.addEvent("found managed subscription", {
        id: existingSubscription.id,
      });
      this.logger.debug(
        { id: existingSubscription.id },
        "Located existing managed subscription in database",
      );

      const expiresAt = new Date(existingSubscription.expiresAt);
      const now = new Date();
      const diffFromNow = expiresAt.getTime() - now.getTime();

      span?.setAttribute("subscription.expiresAt", expiresAt.toISOString());
      span?.setAttribute("subscription.diffFromNowMs", diffFromNow);

      this.logger.debug(
        { id: existingSubscription.id, expiresAt, now: now, diffFromNow },
        "Evaluating managed subscription expiration status",
      );

      // NOTE: 15 minutes is the last possible time we can get lifecycle notifications from Microsoft Graph
      // beyond that, we risk missing the notification and thus missing the chance to renew the subscription
      // automatically. In practice, we should aim to renew well before that to avoid any risk of missing it.
      // This threshold gives marks that last point to understand whether we should force a new subscription
      // or just keep it as is.
      const minimalTimeForLifecycleNotificationsInMinutes = 15;
      if (diffFromNow < 0) {
        span?.addEvent("subscription expired, deleting");

        const result = await this.db
          .delete(subscriptions)
          .where(eq(subscriptions.id, existingSubscription.id));

        span?.addEvent("expired managed subscription deleted", {
          id: existingSubscription.id,
          count: result.rowCount ?? NaN,
        });

        this.logger.log(
          { id: existingSubscription.id, count: result.rowCount ?? NaN },
          "Successfully deleted expired managed subscription from database",
        );
        // Continue to create a new subscription below
      } else if (
        diffFromNow <=
        minimalTimeForLifecycleNotificationsInMinutes * 60 * 1000
      ) {
        // NOTE: here we are below the threshold and ideally we should also be discarding the existing subscription
        // but there might be an edge case where this event gets picked up while a renewal is already in progress or
        // is about to happen very soon - this is a very unlikely edge case (never happened in prod),
        // but to be safe we just skip creating a new subscription here and let it naturally renew later or eventually expire.
        span?.addEvent("subscription expiration below renewal threshold", {
          id: existingSubscription.id,
          thresholdMinutes: minimalTimeForLifecycleNotificationsInMinutes,
        });

        this.logger.warn(
          {
            id: existingSubscription.id,
            thresholdMinutes: minimalTimeForLifecycleNotificationsInMinutes,
          },
          "Subscription expires too soon to renew safely, returning existing",
        );
        return { status: "expiring_soon", subscription: existingSubscription };
      } else {
        // NOTE: here we have enough time left on the subscription, so we do nothing
        span?.addEvent("subscription valid, skipping creation");

        this.logger.debug(
          { id: existingSubscription.id },
          "Existing subscription is valid, skipping new subscription creation",
        );
        return { status: "already_active", subscription: existingSubscription };
      }
    }

    span?.addEvent("no existing subscription found");
    this.logger.debug(
      {},
      "No existing subscription found, proceeding with new subscription creation",
    );

    const { notificationUrl, lifecycleNotificationUrl } =
      this.utils.getSubscriptionURLs();
    const nextScheduledExpiration = this.utils.getNextScheduledExpiration();
    const webhookSecret = this.utils.getWebhookSecret();

    const userProfile = await this.db.query.userProfiles.findFirst({
      columns: {
        providerUserId: true,
        email: true,
      },
      where: eq(userProfiles.id, userProfileId.toString()),
    });

    if (!userProfile) {
      span?.addEvent("user profile not found");
      this.logger.error(
        { userProfileId: userProfileId.toString() },
        "Cannot proceed: user profile does not exist in database",
      );
      assert.fail(`${userProfileId} could not be found on DB`);
    }

    span?.setAttribute(
      "user_profile.provider_user_id",
      userProfile.providerUserId,
    );
    this.logger.debug(
      { providerUserId: userProfile.providerUserId },
      "Successfully retrieved user profile from database",
    );

    const payload = await CreateSubscriptionRequestSchema.encodeAsync({
      changeType: ["created"],
      notificationUrl,
      lifecycleNotificationUrl,
      clientState: webhookSecret,
      resource: `users/${userProfile.providerUserId}/messages`,
      expirationDateTime: nextScheduledExpiration,
    });

    span?.addEvent("new subscription payload prepared", {
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
      "Prepared Microsoft Graph subscription request payload",
    );

    this.logger.debug(
      { resource: payload.resource, changeType: payload.changeType },
      "Sending subscription creation request to Microsoft Graph API",
    );

    const client = this.graphClientFactory.createClientForUser(
      userProfileId.toString(),
    );
    const graphResponse = (await client
      .api("/subscriptions")
      .post(payload)) as unknown;
    const graphSubscription = await Subscription.parseAsync(graphResponse);

    span?.setAttribute("graph_subscription.id", graphSubscription.id);
    span?.addEvent("Graph API subscription created", {
      subscriptionId: graphSubscription.id,
    });

    this.logger.log(
      { subscriptionId: graphSubscription.id },
      "Microsoft Graph API subscription was created successfully",
    );

    const newManagedSubscriptions = await this.db
      .insert(subscriptions)
      .values({
        internalType: "mail_monitoring",
        expiresAt: graphSubscription.expirationDateTime,
        userProfileId: userProfileId.toString(),
        subscriptionId: graphSubscription.id,
      })
      .returning();

    const created = newManagedSubscriptions.at(0);
    if (!created) {
      span?.addEvent("failed to create managed subscription in DB");
      assert.fail("subscription was not created");
    }

    span?.addEvent("new managed subscription created", { id: created.id });
    this.logger.log(
      { id: created.id },
      "Successfully created new managed subscription record",
    );

    // assert.ok(userProfile.email, `User has no emails`);
    // await this.fetchOrCreateOutlookEmailsRootScopeCommand.run(
    //   userProfile.email,
    // );
    // const syncStats = await this.db.query.mailFoldersSync.findFirst({
    //   where: eq(mailFoldersSync.userProfileId, userProfileId.toString()),
    // });
    // if (!syncStats) {
    //   this.db
    //     .insert(mailFoldersSync)
    //     .values({ userProfileId: userProfileId.toString() });
    // }

    return { status: "created", subscription: created };
  }
}
