import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { BatchResponseContent } from '@microsoft/microsoft-graph-client';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MicrosoftGraphErrorSchema, makeGraphError } from '~/msgraph/graph-error';
import { UniqueService } from '~/unique/unique.service';
import {
  BatchRequest,
  CreatedEventDto,
  Meeting,
  RecordingCollection,
  Transcript,
  TranscriptResourceSchema,
  TranscriptVttMetadataSchema,
} from './transcript.dtos';

@Injectable()
export class TranscriptCreatedService {
  private readonly logger = new Logger(TranscriptCreatedService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly unique: UniqueService,
  ) {}

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

    assert.ok(published, `Cannot publish AMQP event "${payload.type}"`);
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
