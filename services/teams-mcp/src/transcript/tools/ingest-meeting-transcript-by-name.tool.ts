import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import {
  type CalendarEvent,
  CalendarEventCollection,
  type Meeting,
  MeetingCollection,
  type Transcript,
  TranscriptCollection,
} from '../transcript.dtos';
import { TranscriptCreatedService } from '../transcript-created.service';

const IngestMeetingTranscriptByNameInputSchema = z.object({
  subject: z
    .string()
    .describe('Search term to match against meeting subject (case-insensitive contains match)'),
  startDateTime: z
    .string()
    .datetime()
    .optional()
    .describe('Start of search range (ISO 8601). Defaults to start of today UTC.'),
  endDateTime: z
    .string()
    .datetime()
    .optional()
    .describe('End of search range (ISO 8601). Defaults to end of today UTC.'),
});

const MeetingSummarySchema = z.custom<Meeting>().transform((m) => ({
  id: m.id,
  subject: m.subject ?? 'Untitled Meeting',
  startDateTime: m.startDateTime.toISOString(),
  endDateTime: m.endDateTime.toISOString(),
  organizer: {
    id: m.participants.organizer.identity.user.id,
    displayName: m.participants.organizer.identity.user.displayName ?? null,
    email: m.participants.organizer.upn,
  },
  participantCount: m.participants.attendees.length,
}));

const IngestedTranscriptSchema = z.custom<Transcript>().transform((t) => ({
  id: t.id,
  createdDateTime: t.createdDateTime.toISOString(),
  endDateTime: t.endDateTime.toISOString(),
}));

const IngestedTranscriptResultSchema = z.object({
  id: z.string(),
  createdDateTime: z.string(),
  endDateTime: z.string(),
  status: z.enum(['ingested', 'failed']),
  error: z.string().optional(),
});
type IngestedTranscriptResult = z.infer<typeof IngestedTranscriptResultSchema>;

const MeetingSummaryOutputSchema = z.object({
  id: z.string(),
  subject: z.string(),
  startDateTime: z.string(),
  endDateTime: z.string(),
  organizer: z.object({
    id: z.string(),
    displayName: z.string().nullable(),
    email: z.string(),
  }),
  participantCount: z.number(),
});

const MeetingResultSchema = z.object({
  meeting: MeetingSummaryOutputSchema,
  transcripts: z.array(IngestedTranscriptResultSchema),
});
type MeetingResult = z.infer<typeof MeetingResultSchema>;

const IngestMeetingTranscriptByNameOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  meetings: z.array(MeetingResultSchema),
});

function todayStartUTC(): string {
  const now = new Date();
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()),
  ).toISOString();
}

function todayEndUTC(): string {
  const now = new Date();
  return new Date(
    Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 23, 59, 59, 999),
  ).toISOString();
}

@Injectable()
export class IngestMeetingTranscriptByNameTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly transcriptCreatedService: TranscriptCreatedService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'ingest_meeting_transcript_by_name',
    title: 'Ingest Meeting Transcript by Name',
    description:
      'Searches for Teams meetings by subject name within a date range (defaults to today), then fetches and ingests their transcripts into the knowledge base.',
    parameters: IngestMeetingTranscriptByNameInputSchema,
    outputSchema: IngestMeetingTranscriptByNameOutputSchema,
    annotations: {
      title: 'Ingest Meeting Transcript by Name',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'transcript',
      'unique.app/system-prompt':
        'Searches for Teams meetings by subject name and ingests their transcripts. Use this when a user refers to a meeting by name (e.g. "ingest today\'s standup transcript") rather than providing a direct meeting link.',
    },
  })
  @Span()
  public async ingestMeetingTranscriptByName(
    input: z.infer<typeof IngestMeetingTranscriptByNameInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('subject_search', input.subject);

    const startDateTime = input.startDateTime ?? todayStartUTC();
    const endDateTime = input.endDateTime ?? todayEndUTC();

    span?.setAttribute('start_date_time', startDateTime);
    span?.setAttribute('end_date_time', endDateTime);

    this.logger.log(
      { subject: input.subject, startDateTime, endDateTime },
      'Starting transcript ingestion by meeting name',
    );

    const calendarEvents = await this.searchCalendarEvents(
      userProfileId,
      startDateTime,
      endDateTime,
    );

    const matchingEvents = this.filterBySubject(calendarEvents, input.subject);
    if (matchingEvents.length === 0) {
      this.logger.warn(
        { subject: input.subject, startDateTime, endDateTime, totalEvents: calendarEvents.length },
        'No meetings matching subject found in date range',
      );
      return {
        success: false,
        message: `No meetings matching "${input.subject}" found between ${startDateTime} and ${endDateTime}.`,
        meetings: [],
      };
    }

    span?.setAttribute('matching_events_count', matchingEvents.length);
    this.logger.log(
      { matchingCount: matchingEvents.length, subject: input.subject },
      'Found matching calendar events, resolving online meetings',
    );

    const meetingResults: MeetingResult[] = [];

    for (const event of matchingEvents) {
      const joinUrl = event.onlineMeeting?.joinUrl.toString();
      if (!joinUrl) continue;

      const meeting = await this.findMeetingByJoinUrl(userProfileId, joinUrl);
      if (!meeting) {
        this.logger.warn(
          { joinUrl, eventSubject: event.subject },
          'Could not resolve online meeting from calendar event join URL',
        );
        continue;
      }

      const summary = MeetingSummarySchema.parse(meeting);

      const transcripts = await this.listTranscripts(userProfileId, meeting.id);
      if (transcripts.length === 0) {
        this.logger.debug(
          { meetingId: meeting.id, subject: meeting.subject },
          'No transcripts available for meeting',
        );
        meetingResults.push({ meeting: summary, transcripts: [] });
        continue;
      }

      this.logger.log(
        { meetingId: meeting.id, subject: meeting.subject, transcriptCount: transcripts.length },
        'Found transcripts, starting ingestion',
      );

      const results = await this.ingestTranscripts(userProfileId, meeting, transcripts);
      meetingResults.push({ meeting: summary, transcripts: results });
    }

    const totalIngested = meetingResults.reduce(
      (sum, r) => sum + r.transcripts.filter((t) => t.status === 'ingested').length,
      0,
    );
    const totalFailed = meetingResults.reduce(
      (sum, r) => sum + r.transcripts.filter((t) => t.status === 'failed').length,
      0,
    );
    const totalTranscripts = meetingResults.reduce((sum, r) => sum + r.transcripts.length, 0);

    span?.setAttribute('total_meetings', meetingResults.length);
    span?.setAttribute('total_ingested', totalIngested);
    span?.setAttribute('total_failed', totalFailed);

    this.logger.log(
      {
        subject: input.subject,
        meetingCount: meetingResults.length,
        totalIngested,
        totalFailed,
        totalTranscripts,
      },
      'Completed transcript ingestion by name',
    );

    return {
      success: totalIngested > 0,
      message: `Found ${meetingResults.length} meeting(s) matching "${input.subject}". Ingested ${totalIngested} of ${totalTranscripts} transcript(s).`,
      meetings: meetingResults,
    };
  }

  private async searchCalendarEvents(
    userProfileId: string,
    startDateTime: string,
    endDateTime: string,
  ): Promise<CalendarEvent[]> {
    this.logger.debug({ startDateTime, endDateTime }, 'Querying calendar view from Graph API');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api('/me/calendarView')
      .query({ startDateTime, endDateTime })
      .get();

    const collection = await CalendarEventCollection.parseAsync(response);

    this.logger.debug({ eventCount: collection.value.length }, 'Retrieved calendar events');

    return collection.value;
  }

  private filterBySubject(events: CalendarEvent[], subject: string): CalendarEvent[] {
    const search = subject.toLowerCase();
    const matching = events.filter(
      (e) => e.subject?.toLowerCase().includes(search) && e.onlineMeeting != null,
    );

    this.logger.debug(
      { search, totalEvents: events.length, matchingEvents: matching.length },
      'Filtered calendar events by subject and online meeting presence',
    );

    return matching;
  }

  private async findMeetingByJoinUrl(
    userProfileId: string,
    joinWebUrl: string,
  ): Promise<Meeting | null> {
    this.logger.debug({ joinWebUrl }, 'Looking up meeting by join URL via Graph API');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api('/me/onlineMeetings')
      .filter(`JoinWebUrl eq '${joinWebUrl}'`)
      .get();

    const collection = await MeetingCollection.parseAsync(response);
    const meeting = collection.value.at(0) ?? null;

    if (!meeting) {
      this.logger.debug({ joinWebUrl }, 'No meeting matched the join URL');
    } else {
      this.logger.debug(
        { meetingId: meeting.id, subject: meeting.subject },
        'Resolved meeting from join URL',
      );
    }

    return meeting;
  }

  private async listTranscripts(userProfileId: string, meetingId: string): Promise<Transcript[]> {
    this.logger.debug({ meetingId }, 'Fetching transcript list from Graph API');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client.api(`/me/onlineMeetings/${meetingId}/transcripts`).get();
    const collection = await TranscriptCollection.parseAsync(response);

    this.logger.debug(
      { meetingId, transcriptCount: collection.value.length },
      'Retrieved transcript list',
    );

    return collection.value;
  }

  private async ingestTranscripts(
    userProfileId: string,
    meeting: Meeting,
    transcripts: Transcript[],
  ): Promise<IngestedTranscriptResult[]> {
    const results: IngestedTranscriptResult[] = [];

    for (const transcript of transcripts) {
      results.push(await this.ingestSingleTranscript(userProfileId, meeting, transcript));
    }

    return results;
  }

  private async ingestSingleTranscript(
    userProfileId: string,
    meeting: Meeting,
    transcript: Transcript,
  ): Promise<IngestedTranscriptResult> {
    const base = IngestedTranscriptSchema.parse(transcript);

    try {
      this.logger.debug(
        { transcriptId: transcript.id, meetingId: meeting.id },
        'Ingesting transcript',
      );

      await this.transcriptCreatedService.fetchVttAndIngest(userProfileId, meeting, transcript);

      this.logger.log(
        { transcriptId: transcript.id, meetingId: meeting.id },
        'Successfully ingested transcript',
      );

      return { ...base, status: 'ingested' };
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.logger.error(
        { transcriptId: transcript.id, meetingId: meeting.id, error: errorMessage },
        'Failed to ingest transcript',
      );

      return { ...base, status: 'failed', error: errorMessage };
    }
  }
}
