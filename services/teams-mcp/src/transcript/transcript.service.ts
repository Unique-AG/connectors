import path from 'node:path';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { BatchResponseContent } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import type { TypeID } from 'typeid-js';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import type { AppConfigNamespaced, MicrosoftConfigNamespaced } from '~/config';
import { DRIZZLE, type DrizzleDatabase, subscriptions, userProfiles } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MicrosoftGraphErrorSchema, makeGraphError } from '~/msgraph/graph-error';
import { UniqueService } from '~/unique/unique.service';
import type { Redacted } from '~/utils/redacted';
import {
  BatchRequest,
  CreatedEventDto,
  CreateSubscriptionRequestSchema,
  Meeting,
  ReauthorizationRequiredEventDto,
  RecordingCollection,
  Subscription,
  SubscriptionRemovedEventDto,
  SubscriptionRequestedEventDto,
  Transcript,
  TranscriptResourceSchema,
  TranscriptVttMetadataSchema,
  UpdateSubscriptionRequestSchema,
} from './transcript.dtos';

@Injectable()
export class TranscriptService {
  private readonly logger = new Logger(TranscriptService.name);

  public constructor(
    private readonly config: ConfigService<AppConfigNamespaced & MicrosoftConfigNamespaced, true>,
    private readonly amqp: AmqpConnection,
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly unique: UniqueService,
  ) {}

  public isWebhookTrustedViaState(state: Redacted<string> | null): boolean {
    const webhookSecret = this.config.get('microsoft.webhookSecret', {
      infer: true,
    });

    const isTrusted = state === null || state.value === webhookSecret.value;

    this.logger.debug({ isTrusted, hasState: state !== null }, 'webhook trust validation');
    const span = this.trace.getSpan();
    span?.setAttribute('isTrusted', isTrusted);

    return isTrusted;
  }

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

    const { notificationUrl, lifecycleNotificationUrl } = this.getSubscriptionURLs();

    const nextScheduledExpiration = this.getNextScheduledExpiration();

    const webhookSecret = this.config.get('microsoft.webhookSecret', {
      infer: true,
    });

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

  private getSubscriptionURLs(): {
    notificationUrl: URL;
    lifecycleNotificationUrl: URL;
  } {
    const publicWebhookUrl = this.config.get('microsoft.publicWebhookUrl', { infer: true });

    const notificationUrl = new URL(
      path.join(publicWebhookUrl.pathname, 'transcript/notification'),
      publicWebhookUrl,
    );
    const lifecycleNotificationUrl = new URL(
      path.join(publicWebhookUrl.pathname, 'transcript/lifecycle'),
      publicWebhookUrl,
    );

    this.logger.debug(
      {
        notificationUrl: notificationUrl.toString(),
        lifecycleNotificationUrl: lifecycleNotificationUrl.toString(),
      },
      'subscription URLs generated',
    );

    return {
      notificationUrl,
      lifecycleNotificationUrl,
    };
  }

  private getNextScheduledExpiration(): Date {
    // NOTE: requires to be at least 2 hours in the future or we won't be getting lifecycle notifications
    const lifecycleHoursRequired = 2;
    const targetHour = 3; // TODO: can extract to a module option at somepoint

    const now = new Date();
    // build today's target (3:00:00.000 UTC)
    const nextThreeAM = new Date(
      Date.UTC(
        now.getUTCFullYear(),
        now.getUTCMonth(),
        now.getUTCDate(),
        targetHour, // hour
        0, // minute
        0, // second
        0, // ms
      ),
    );

    const nowHour = now.getUTCHours();
    const needsNextDay = nowHour >= targetHour || nowHour + lifecycleHoursRequired >= targetHour;
    if (needsNextDay) {
      nextThreeAM.setUTCDate(nextThreeAM.getUTCDate() + 1);
    }

    this.logger.debug(
      {
        now,
        nextThreeAM,
      },
      'next scheduled expiration',
    );

    return nextThreeAM;
  }

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

    if (!published) throw new Error(`Cannot publish AMQP event "${payload.type}"`);
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

    const nextScheduledExpiration = this.getNextScheduledExpiration();

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

  @Span()
  public async enqueueCreated(subscriptionId: string, resource: string) {
    const span = this.trace.getSpan();
    span?.setAttribute('subscriptionId', subscriptionId);
    span?.setAttribute('resource', resource);

    this.logger.debug({ subscriptionId, resource }, 'enqueuing transcript created event');

    const payload = await CreatedEventDto.encodeAsync({
      subscriptionId,
      resource,
      type: 'unique.teams-mcp.transcript.change-notification.created',
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
  public async created(subscriptionId: string, resource: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscriptionId', subscriptionId);
    span?.setAttribute('resource', resource);

    this.logger.debug({ subscriptionId, resource }, 'processing transcript created notification');

    const { userId, meetingId, transcriptId } = await TranscriptResourceSchema.parseAsync(resource);

    span?.setAttribute('userId', userId);
    span?.setAttribute('meetingId', meetingId);
    span?.setAttribute('transcriptId', transcriptId);

    this.logger.debug(
      { userId, meetingId, transcriptId },
      'parsed transcript resource identifiers',
    );

    const subscription = await this.db.query.subscriptions.findFirst({
      where: and(
        eq(subscriptions.internalType, 'transcript'),
        eq(subscriptions.subscriptionId, subscriptionId),
      ),
      with: { userProfile: true },
    });

    if (!subscription) {
      span?.addEvent('subscription not found');

      this.logger.warn(
        { subscriptionId },
        "the created transcript is for a subscription we don't manage",
      );
      return;
    }

    span?.setAttribute('userProfileId', subscription.userProfileId);
    this.logger.debug(
      { subscriptionId, userProfileId: subscription.userProfileId },
      'found managed subscription',
    );

    const client = this.graphClientFactory.createClientForUser(subscription.userProfileId);

    this.logger.debug(
      { userId, meetingId, transcriptId },
      'preparing batch request for transcript data',
    );

    const payload = await BatchRequest.encodeAsync({
      requests: [
        {
          id: 'meetingData',
          url: `/users/${userId}/onlineMeetings/${meetingId}`,
          method: 'GET',
        },
        {
          id: 'transcriptData',
          url: `/users/${userId}/onlineMeetings/${meetingId}/transcripts/${transcriptId}`,
          method: 'GET',
        },
        {
          id: 'transcriptContent',
          url: `/users/${userId}/onlineMeetings/${meetingId}/transcripts/${transcriptId}/content`,
          method: 'GET',
          headers: { Accept: 'text/vtt' },
        },
        {
          id: 'transcriptMeta',
          url: `/users/${userId}/onlineMeetings/${meetingId}/transcripts/${transcriptId}/metadataContent`,
          method: 'GET',
          headers: { Accept: 'text/vtt' },
        },
      ],
    });
    const batch = await client
      .api('/$batch')
      .post(payload)
      .then((res) => new BatchResponseContent(res));

    span?.addEvent('batch request completed');

    const meetingDataResponse = batch.getResponseById('meetingData');
    if (!meetingDataResponse.ok) {
      const error = await meetingDataResponse.json().then(MicrosoftGraphErrorSchema.parseAsync);
      throw makeGraphError(error, meetingDataResponse.status, meetingDataResponse.headers);
    }
    const meeting = await meetingDataResponse.json().then(Meeting.parseAsync);
    span?.addEvent('meeting data retrieved');
    this.logger.debug({ meetingId }, 'meeting data retrieved');

    const transcriptDataResponse = batch.getResponseById('transcriptData');
    if (!transcriptDataResponse.ok) {
      const error = await transcriptDataResponse.json().then(MicrosoftGraphErrorSchema.parseAsync);
      throw makeGraphError(error, transcriptDataResponse.status, transcriptDataResponse.headers);
    }
    const transcript = await transcriptDataResponse.json().then(Transcript.parseAsync);
    span?.addEvent('transcript data retrieved');
    this.logger.debug(
      { transcriptId, contentCorrelationId: transcript.contentCorrelationId },
      'transcript data retrieved',
    );

    const transcriptContentResponse = batch.getResponseById('transcriptContent');
    if (!transcriptContentResponse.ok) {
      const error = await transcriptContentResponse
        .json()
        .then(MicrosoftGraphErrorSchema.parseAsync);
      throw makeGraphError(
        error,
        transcriptContentResponse.status,
        transcriptContentResponse.headers,
      );
    }
    const vttStream = transcriptContentResponse.body;
    span?.addEvent('transcript content retrieved', { hasVtt: !!vttStream });
    this.logger.debug({ hasVtt: !!vttStream }, 'transcript VTT content retrieved');
    if (!vttStream) throw new Error('expected a vtt transcript body');

    const transcriptMetaResponse = batch.getResponseById('transcriptMeta');
    if (!transcriptMetaResponse.ok) {
      const error = await transcriptMetaResponse.json().then(MicrosoftGraphErrorSchema.parseAsync);
      throw makeGraphError(error, transcriptMetaResponse.status, transcriptMetaResponse.headers);
    }
    const _meta = await transcriptMetaResponse.text().then(TranscriptVttMetadataSchema.parseAsync);
    span?.addEvent('transcript metadata retrieved');
    this.logger.debug('transcript metadata retrieved');

    let recordingStream: ReadableStream<Uint8Array<ArrayBuffer>> | undefined;
    try {
      this.logger.debug(
        { contentCorrelationId: transcript.contentCorrelationId },
        'attempting to retrieve recording',
      );

      const recordingResponse = await client
        .api(`users/${userId}/onlineMeetings/${meetingId}/recordings`)
        .filter(`contentCorrelationId eq '${transcript.contentCorrelationId}'`)
        .get();

      const recordingData = await RecordingCollection.refine(
        (r) => r.value.length > 0,
        'correlated recording was not found',
      )
        // biome-ignore lint/style/noNonNullAssertion: checked above
        .transform((rc) => rc.value[0]!)
        .parseAsync(recordingResponse);

      span?.setAttribute('recording.id', recordingData.id);
      this.logger.debug({ recordingId: recordingData.id }, 'found correlated recording');

      recordingStream = await client
        .api(
          `/v1.0/users/${userId}/onlineMeetings/${meetingId}/recordings/${recordingData.id}/content`,
        )
        .getStream();

      span?.addEvent('recording content retrieved');
      this.logger.log({ recordingId: recordingData.id }, 'recording content retrieved');
    } catch (error) {
      span?.addEvent('failed to retrieve recording', {
        error: error instanceof Error ? error.message : String(error),
      });

      this.logger.warn({ error }, 'unable to get recording content');
    }

    span?.addEvent('transcript processing completed', {
      hasRecording: recordingStream !== undefined,
    });

    await this.unique.ingestTranscript(
      {
        subject: meeting.subject ?? '',
        startDateTime: meeting.startDateTime,
        endDateTime: meeting.endDateTime,
        owner: {
          name: meeting.participants.organizer.identity.user.displayName ?? '',
          email: meeting.participants.organizer.upn,
        },
        participants: meeting.participants.attendees.map((p) => ({
          name: p.identity.user.displayName ?? '',
          email: p.upn,
        })),
      },
      { id: transcript.id, content: vttStream },
    );
  }
}
