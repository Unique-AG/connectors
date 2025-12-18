import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueService } from '~/unique/unique.service';
import { normalizeError } from '~/utils/normalize-error';
import {
  CreatedEventDto,
  Meeting,
  RecordingCollection,
  Transcript,
  TranscriptResourceSchema,
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
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('resource', resource);
    span?.setAttribute('operation', 'enqueue_created');

    this.logger.debug(
      { subscriptionId, resource },
      'Enqueuing transcript creation event for processing',
    );

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
  public async created(subscriptionId: string, resource: string): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('subscription_id', subscriptionId);
    span?.setAttribute('resource', resource);
    span?.setAttribute('operation', 'process_created');

    this.logger.log(
      { subscriptionId, resource },
      'Processing transcript creation notification from Microsoft Graph',
    );

    const { userId, meetingId, transcriptId } = await TranscriptResourceSchema.parseAsync(resource);

    span?.setAttribute('user_id', userId);
    span?.setAttribute('meeting_id', meetingId);
    span?.setAttribute('transcript_id', transcriptId);

    this.logger.debug(
      { userId, meetingId, transcriptId },
      'Successfully parsed transcript resource identifiers from Microsoft Graph',
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
        'Transcript belongs to a subscription not managed by this service',
      );
      return;
    }

    span?.setAttribute('user_profile_id', subscription.userProfileId);
    this.logger.debug(
      { subscriptionId, userProfileId: subscription.userProfileId },
      'Located managed subscription record in database',
    );

    const client = this.graphClientFactory.createClientForUser(subscription.userProfileId);

    this.logger.debug(
      { userId, meetingId, transcriptId },
      'Retrieving transcript data from Microsoft Graph using parallel API calls',
    );

    const [meeting, transcript, vttStream] = await Promise.all([
      client.api(`/users/${userId}/onlineMeetings/${meetingId}`).get().then(Meeting.parseAsync),
      client
        .api(`/users/${userId}/onlineMeetings/${meetingId}/transcripts/${transcriptId}`)
        .get()
        .then(Transcript.parseAsync),
      client
        .api(`/users/${userId}/onlineMeetings/${meetingId}/transcripts/${transcriptId}/content`)
        .header('Accept', 'text/vtt')
        .getStream(),
    ]);

    span?.addEvent('microsoft graph data retrieved', {
      meetingId,
      transcriptId,
      contentCorrelationId: transcript.contentCorrelationId,
      hasVtt: !!vttStream,
    });
    this.logger.debug(
      {
        meetingId,
        transcriptId,
        contentCorrelationId: transcript.contentCorrelationId,
        hasVtt: !!vttStream,
      },
      'Successfully retrieved data from Microsoft Graph',
    );
    assert.ok(vttStream, 'expected a vtt transcript body');

    let recording: { id:string, content: ReadableStream<Uint8Array<ArrayBuffer>> } | undefined;
    try {
      this.logger.debug(
        { contentCorrelationId: transcript.contentCorrelationId },
        'Attempting to retrieve correlated meeting recording from Microsoft Graph',
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
      this.logger.debug(
        { recordingId: recordingData.id },
        'Located correlated meeting recording in Microsoft Graph',
      );

      recording = {
        id: recordingData.id,
        content: await client
          .api(
            `/v1.0/users/${userId}/onlineMeetings/${meetingId}/recordings/${recordingData.id}/content`,
          )
          .getStream(),
      };

      span?.addEvent('recording content retrieved');
      this.logger.debug(
        { recordingId: recordingData.id },
        'Successfully downloaded meeting recording content',
      );
    } catch (error) {
      span?.addEvent('failed to retrieve recording', {
        error: error instanceof Error ? error.message : String(error),
      });

      this.logger.warn(
        { error: serializeError(normalizeError(error)) },
        'Failed to retrieve or locate meeting recording, proceeding without it',
      );
    }

    span?.addEvent('transcript processing completed', {
      hasRecording: recording !== undefined,
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
      recording ? { id: recording.id, content: recording.content } : undefined,
    );
  }
}
