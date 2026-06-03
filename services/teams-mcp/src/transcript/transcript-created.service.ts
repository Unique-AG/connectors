import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import type { TypeID } from 'typeid-js';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueService } from '~/unique/unique.service';
import {
  CreatedEventDto,
  IngestRequestedEventDto,
  Meeting,
  Transcript,
  TranscriptResourceSchema,
} from './transcript.dtos';
import { TranscriptRecordingService } from './transcript-recording.service';

@Injectable()
export class TranscriptCreatedService {
  private readonly logger = new Logger(TranscriptCreatedService.name);

  public constructor(
    private readonly amqp: AmqpConnection,
    private readonly trace: TraceService,
    @Inject(DRIZZLE) private readonly db: DrizzleDatabase,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly unique: UniqueService,
    private readonly recordingService: TranscriptRecordingService,
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

    // The webhook path runs as the subscribed token owner (userId == token owner), so the
    // `/users/${userId}/...` routes behave like `/me`. Keep them unchanged here.
    await this.processTranscript(
      subscription.userProfileId,
      `/users/${userId}`,
      meetingId,
      transcriptId,
    );
  }

  @Span()
  public async enqueueIngestRequested(args: {
    userProfileId: TypeID<'user_profile'>;
    meetingId: string;
    transcriptId: string;
  }): Promise<void> {
    const { userProfileId, meetingId, transcriptId } = args;

    const span = this.trace.getSpan();
    span?.setAttribute('user_profile_id', userProfileId.toString());
    span?.setAttribute('meeting_id', meetingId);
    span?.setAttribute('transcript_id', transcriptId);
    span?.setAttribute('operation', 'enqueue_ingest_requested');

    this.logger.debug(
      { userProfileId: userProfileId.toString(), meetingId, transcriptId },
      'Enqueuing on-demand transcript ingest request for processing',
    );

    const payload = await IngestRequestedEventDto.encodeAsync({
      userProfileId,
      meetingId,
      transcriptId,
      type: 'unique.teams-mcp.transcript.change-notification.ingest-requested',
    });

    const published = await this.amqp.publish(MAIN_EXCHANGE.name, payload.type, payload, {});

    span?.setAttribute('published', published);
    span?.addEvent('event published to AMQP', {
      exchangeName: MAIN_EXCHANGE.name,
      eventType: payload.type,
      published,
    });

    this.logger.debug(
      { exchangeName: MAIN_EXCHANGE.name, payload, published },
      'Publishing event to message queue for asynchronous processing',
    );

    assert.ok(published, `Cannot publish AMQP event "${payload.type}"`);
  }

  @Span()
  public async ingestRequested(event: IngestRequestedEventDto): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('user_profile_id', event.userProfileId.toString());
    span?.setAttribute('meeting_id', event.meetingId);
    span?.setAttribute('transcript_id', event.transcriptId);
    span?.setAttribute('operation', 'process_ingest_requested');

    this.logger.log(
      {
        userProfileId: event.userProfileId.toString(),
        meetingId: event.meetingId,
        transcriptId: event.transcriptId,
      },
      'Processing on-demand transcript ingest request',
    );

    // The on-demand path runs as the caller's delegated token; the caller may be an invited
    // attendee rather than the organizer, so resolve everything via `/me/...` routes.
    await this.processTranscript(
      event.userProfileId.toString(),
      '/me',
      event.meetingId,
      event.transcriptId,
    );
  }

  /**
   * Shared ingest core for both the webhook ({@link created}) and on-demand
   * ({@link ingestRequested}) paths.
   *
   * `ownerPath` is the Graph route prefix used to reach the meeting: `/me` for the on-demand
   * delegated path, or `/users/${userId}` for the webhook path (where the token owner == userId).
   */
  private async processTranscript(
    userProfileId: string,
    ownerPath: string,
    meetingId: string,
    transcriptId: string,
  ): Promise<void> {
    const span = this.trace.getSpan();

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    this.logger.debug(
      { userProfileId, ownerPath, meetingId, transcriptId },
      'Retrieving transcript data from Microsoft Graph using parallel API calls',
    );

    const [meeting, transcript] = await Promise.all([
      client.api(`${ownerPath}/onlineMeetings/${meetingId}`).get().then(Meeting.parseAsync),
      client
        .api(`${ownerPath}/onlineMeetings/${meetingId}/transcripts/${transcriptId}`)
        .get()
        .then(Transcript.parseAsync),
    ]);

    span?.addEvent('microsoft graph data retrieved', {
      meetingId,
      transcriptId,
      contentCorrelationId: transcript.contentCorrelationId,
    });
    this.logger.debug(
      {
        meetingId,
        transcriptId,
        contentCorrelationId: transcript.contentCorrelationId,
      },
      'Successfully retrieved data from Microsoft Graph',
    );

    span?.addEvent('transcript processing completed');

    // Fetch the correlated recording (if available) before ingesting
    const recording = await this.recordingService.fetchRecording(
      userProfileId,
      ownerPath,
      meetingId,
      transcript.contentCorrelationId,
    );

    await this.unique.ingestTranscript(
      {
        meetingId,
        subject: meeting.subject ?? '',
        // onlineMeetings/{id}.startDateTime returns the master/scheduled time, which
        // collapses every occurrence of a recurring meeting into one YYYY-MM-DD folder.
        // Use the transcript time so each occurrence gets its own folder.
        date: transcript.createdDateTime,
        startDateTime: transcript.createdDateTime,
        endDateTime: transcript.endDateTime,
        contentCorrelationId: transcript.contentCorrelationId,
        owner: {
          id: meeting.participants.organizer.identity.user.id,
          name: meeting.participants.organizer.identity.user.displayName ?? '',
          email: meeting.participants.organizer.upn,
        },
        participants: meeting.participants.attendees.map((p) => ({
          id: p.identity.user.id ?? undefined,
          name: p.identity.user.displayName ?? '',
          email: p.upn,
        })),
      },
      {
        id: transcript.id,
        content: () =>
          client
            .api(`${ownerPath}/onlineMeetings/${meetingId}/transcripts/${transcriptId}/content`)
            .header('Accept', 'text/vtt')
            .getStream(),
      },
      recording ?? undefined,
    );
  }
}
