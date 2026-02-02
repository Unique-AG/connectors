import assert from 'node:assert';
import { AmqpConnection } from '@golevelup/nestjs-rabbitmq';
import { Inject, Injectable, Logger } from '@nestjs/common';
import { and, eq } from 'drizzle-orm';
import { Span, TraceService } from 'nestjs-otel';
import { MAIN_EXCHANGE } from '~/amqp/amqp.constants';
import { DRIZZLE, type DrizzleDatabase, subscriptions } from '~/drizzle';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { UniqueService } from '~/unique/unique.service';
import {
  CalendarEventCollection,
  CreatedEventDto,
  type Meeting,
  type Transcript,
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

    await this.fetchVttAndIngest(
      subscription.userProfileId,
      `/users/${userId}`,
      meeting,
      transcript,
      vttStream,
    );
  }

  /**
   * Fetches calendar event to determine recurrence, then ingests the transcript into Unique.
   *
   * @param userProfileId - User profile ID used to create an authenticated Graph client
   * @param apiPrefix - API path prefix (e.g. `/users/{userId}` or `/me`)
   * @param meeting - Parsed meeting object
   * @param transcript - Parsed transcript metadata
   * @param vttStream - VTT content stream (if already fetched). When not provided, fetches it from Graph API.
   */
  @Span()
  public async fetchVttAndIngest(
    userProfileId: string,
    apiPrefix: string,
    meeting: Meeting,
    transcript: Transcript,
    vttStream?: ReadableStream<Uint8Array<ArrayBuffer>>,
  ): Promise<void> {
    const span = this.trace.getSpan();
    span?.setAttribute('meeting_id', meeting.id);
    span?.setAttribute('transcript_id', transcript.id);
    span?.setAttribute('user_profile_id', userProfileId);

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    if (!vttStream) {
      vttStream = await client
        .api(`${apiPrefix}/onlineMeetings/${meeting.id}/transcripts/${transcript.id}/content`)
        .header('Accept', 'text/vtt')
        .getStream();
      assert.ok(vttStream, 'expected a vtt transcript body');
    }

    // Query events within the meeting time window, then match by threadId client-side
    // (filtering by onlineMeeting properties is not supported by the Graph API)
    const calendarEvents = await client
      .api(`${apiPrefix}/calendarView`)
      .query({
        startDateTime: meeting.startDateTime.toISOString(),
        endDateTime: meeting.endDateTime.toISOString(),
      })
      .get()
      .then(CalendarEventCollection.parseAsync);

    const calendarEvent = calendarEvents.value.find((e) => e.threadId === meeting.threadId);
    const isRecurring =
      calendarEvent?.type === 'occurrence' ||
      calendarEvent?.type === 'exception' ||
      calendarEvent?.type === 'seriesMaster' ||
      !!calendarEvent?.seriesMasterId;

    span?.setAttribute('is_recurring', isRecurring);
    span?.setAttribute('calendar_event_type', calendarEvent?.type ?? 'unknown');
    span?.setAttribute('has_calendar_event', !!calendarEvent);
    this.logger.debug(
      {
        type: calendarEvent?.type,
        calendarEventId: calendarEvent?.id,
        eventType: calendarEvent?.type,
        seriesMasterId: calendarEvent?.seriesMasterId,
        isRecurring,
      },
      'Determined meeting recurrence status from calendar event',
    );

    span?.addEvent('transcript processing completed', { isRecurring });

    await this.unique.ingestTranscript(
      {
        subject: meeting.subject ?? '',
        startDateTime: transcript.createdDateTime,
        endDateTime: transcript.endDateTime,
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
      { id: transcript.id, content: vttStream },
    );
  }
}
