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

const IngestedTranscriptSchema = z.object({
  id: z.string(),
  createdDateTime: z.string(),
  endDateTime: z.string(),
  status: z.enum(['ingested', 'failed']),
  error: z.string().optional(),
});
type IngestedTranscript = z.infer<typeof IngestedTranscriptSchema>;

const MeetingSummarySchema = z.object({
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
  meeting: MeetingSummarySchema,
  transcripts: z.array(IngestedTranscriptSchema),
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

function toMeetingSummary(meeting: Meeting): z.infer<typeof MeetingSummarySchema> {
  return {
    id: meeting.id,
    subject: meeting.subject ?? 'Untitled Meeting',
    startDateTime: meeting.startDateTime.toISOString(),
    endDateTime: meeting.endDateTime.toISOString(),
    organizer: {
      id: meeting.participants.organizer.identity.user.id,
      displayName: meeting.participants.organizer.identity.user.displayName ?? null,
      email: meeting.participants.organizer.upn,
    },
    participantCount: meeting.participants.attendees.length,
  };
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

    const calendarEvents = await this.searchCalendarEvents(
      userProfileId,
      startDateTime,
      endDateTime,
    );

    const matchingEvents = this.filterBySubject(calendarEvents, input.subject);
    if (matchingEvents.length === 0) {
      return {
        success: false,
        message: `No meetings matching "${input.subject}" found between ${startDateTime} and ${endDateTime}.`,
        meetings: [],
      };
    }

    span?.setAttribute('matching_events_count', matchingEvents.length);

    const meetingResults: MeetingResult[] = [];

    for (const event of matchingEvents) {
      const joinUrl = event.onlineMeeting?.joinUrl.toString();
      if (!joinUrl) continue;

      const meeting = await this.findMeetingByJoinUrl(userProfileId, joinUrl);
      if (!meeting) continue;

      const transcripts = await this.listTranscripts(userProfileId, meeting.id);
      if (transcripts.length === 0) {
        meetingResults.push({ meeting: toMeetingSummary(meeting), transcripts: [] });
        continue;
      }

      const results = await this.ingestTranscripts(userProfileId, meeting, transcripts);
      meetingResults.push({ meeting: toMeetingSummary(meeting), transcripts: results });
    }

    const totalIngested = meetingResults.reduce(
      (sum, r) => sum + r.transcripts.filter((t) => t.status === 'ingested').length,
      0,
    );
    const totalTranscripts = meetingResults.reduce((sum, r) => sum + r.transcripts.length, 0);

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
    this.logger.debug({ startDateTime, endDateTime }, 'Searching calendar events');

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
      'Filtered calendar events by subject',
    );

    return matching;
  }

  private async findMeetingByJoinUrl(
    userProfileId: string,
    joinWebUrl: string,
  ): Promise<Meeting | null> {
    this.logger.debug({ joinWebUrl }, 'Looking up meeting by join URL');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client
      .api('/me/onlineMeetings')
      .filter(`JoinWebUrl eq '${joinWebUrl}'`)
      .get();

    const collection = await MeetingCollection.parseAsync(response);
    return collection.value.at(0) ?? null;
  }

  private async listTranscripts(userProfileId: string, meetingId: string): Promise<Transcript[]> {
    this.logger.debug({ meetingId }, 'Listing transcripts for meeting');

    const client = this.graphClientFactory.createClientForUser(userProfileId);
    const response = await client.api(`/me/onlineMeetings/${meetingId}/transcripts`).get();
    const collection = await TranscriptCollection.parseAsync(response);

    this.logger.debug(
      { meetingId, transcriptCount: collection.value.length },
      'Found transcripts for meeting',
    );

    return collection.value;
  }

  private async ingestTranscripts(
    userProfileId: string,
    meeting: Meeting,
    transcripts: Transcript[],
  ): Promise<IngestedTranscript[]> {
    const results: IngestedTranscript[] = [];

    for (const transcript of transcripts) {
      results.push(await this.ingestSingleTranscript(userProfileId, meeting, transcript));
    }

    return results;
  }

  private async ingestSingleTranscript(
    userProfileId: string,
    meeting: Meeting,
    transcript: Transcript,
  ): Promise<IngestedTranscript> {
    try {
      await this.transcriptCreatedService.fetchVttAndIngest(userProfileId, meeting, transcript);

      this.logger.log(
        { transcriptId: transcript.id, meetingId: meeting.id },
        'Successfully ingested transcript',
      );

      return {
        id: transcript.id,
        createdDateTime: transcript.createdDateTime.toISOString(),
        endDateTime: transcript.endDateTime.toISOString(),
        status: 'ingested',
      };
    } catch (error) {
      const errorMessage = error instanceof Error ? error.message : String(error);
      this.logger.error(
        { transcriptId: transcript.id, meetingId: meeting.id, error: errorMessage },
        'Failed to ingest transcript',
      );

      return {
        id: transcript.id,
        createdDateTime: transcript.createdDateTime.toISOString(),
        endDateTime: transcript.endDateTime.toISOString(),
        status: 'failed',
        error: errorMessage,
      };
    }
  }
}
