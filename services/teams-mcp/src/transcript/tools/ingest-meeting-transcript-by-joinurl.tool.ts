import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import {
  type Meeting,
  MeetingCollection,
  type Transcript,
  TranscriptCollection,
} from '../transcript.dtos';
import { TranscriptCreatedService } from '../transcript-created.service';

const IngestMeetingTranscriptByJoinUrlInputSchema = z.object({
  joinWebUrl: z.string().url().describe('The Microsoft Teams meeting join URL'),
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

const IngestMeetingTranscriptByJoinUrlOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  meeting: MeetingSummaryOutputSchema.nullable(),
  transcripts: z.array(IngestedTranscriptResultSchema),
});

@Injectable()
export class IngestMeetingTranscriptByJoinUrlTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly transcriptCreatedService: TranscriptCreatedService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'ingest_meeting_transcript_by_joinurl',
    title: 'Ingest Meeting Transcript by Join URL',
    description:
      'Given a Microsoft Teams meeting link (joinWebUrl), fetches all transcripts for that meeting and ingests them into the knowledge base.',
    parameters: IngestMeetingTranscriptByJoinUrlInputSchema,
    outputSchema: IngestMeetingTranscriptByJoinUrlOutputSchema,
    annotations: {
      title: 'Ingest Meeting Transcript by Join URL',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'transcript',
      'unique.app/system-prompt':
        'Ingests transcripts for a specific Teams meeting identified by its join URL. Use this when a user provides a Teams meeting link and wants the transcript ingested into the knowledge base.',
    },
  })
  @Span()
  public async ingestMeetingTranscriptByJoinUrl(
    input: z.infer<typeof IngestMeetingTranscriptByJoinUrlInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('join_web_url', input.joinWebUrl);

    this.logger.log({ joinWebUrl: input.joinWebUrl }, 'Starting transcript ingestion by join URL');

    const meeting = await this.findMeetingByJoinUrl(userProfileId, input.joinWebUrl);
    if (!meeting) {
      this.logger.warn({ joinWebUrl: input.joinWebUrl }, 'No meeting found for provided join URL');
      return {
        success: false,
        message:
          'No meeting found for the provided join URL. Ensure the URL is correct and you have access to this meeting.',
        meeting: null,
        transcripts: [],
      };
    }

    const summary = MeetingSummarySchema.parse(meeting);

    span?.setAttribute('meeting_id', meeting.id);
    this.logger.log(
      { meetingId: meeting.id, subject: meeting.subject },
      'Found meeting, listing transcripts',
    );

    const transcripts = await this.listTranscripts(userProfileId, meeting.id);
    if (transcripts.length === 0) {
      this.logger.log({ meetingId: meeting.id }, 'Meeting found but no transcripts available');
      return {
        success: true,
        message: 'Meeting found but no transcripts are available for this meeting.',
        meeting: summary,
        transcripts: [],
      };
    }

    span?.setAttribute('transcript_count', transcripts.length);
    this.logger.log(
      { meetingId: meeting.id, transcriptCount: transcripts.length },
      'Found transcripts, starting ingestion',
    );

    // TODO: Use MCP elicitation to let the user pick which transcript when multiple exist
    const results = await this.ingestTranscripts(userProfileId, meeting, transcripts);
    const ingestedCount = results.filter((r) => r.status === 'ingested').length;
    const failedCount = results.filter((r) => r.status === 'failed').length;

    span?.setAttribute('ingested_count', ingestedCount);
    span?.setAttribute('failed_count', failedCount);

    this.logger.log(
      { meetingId: meeting.id, ingestedCount, failedCount, totalCount: results.length },
      'Completed transcript ingestion',
    );

    return {
      success: ingestedCount > 0,
      message: `Ingested ${ingestedCount} of ${results.length} transcript(s) for meeting "${meeting.subject ?? 'Untitled Meeting'}".`,
      meeting: summary,
      transcripts: results,
    };
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
