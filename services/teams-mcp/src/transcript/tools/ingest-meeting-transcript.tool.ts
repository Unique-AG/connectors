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

const IngestMeetingTranscriptInputSchema = z.object({
  joinWebUrl: z.string().url().describe('The Microsoft Teams meeting join URL'),
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

const IngestMeetingTranscriptOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  meeting: MeetingSummarySchema.nullable(),
  transcripts: z.array(IngestedTranscriptSchema),
});

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
export class IngestMeetingTranscriptTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly transcriptCreatedService: TranscriptCreatedService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'ingest_meeting_transcript',
    title: 'Ingest Meeting Transcript',
    description:
      'Given a Microsoft Teams meeting link (joinWebUrl), fetches all transcripts for that meeting and ingests them into the knowledge base.',
    parameters: IngestMeetingTranscriptInputSchema,
    outputSchema: IngestMeetingTranscriptOutputSchema,
    annotations: {
      title: 'Ingest Meeting Transcript',
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
  public async ingestMeetingTranscript(
    input: z.infer<typeof IngestMeetingTranscriptInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('join_web_url', input.joinWebUrl);

    const meeting = await this.findMeetingByJoinUrl(userProfileId, input.joinWebUrl);
    if (!meeting) {
      return {
        success: false,
        message:
          'No meeting found for the provided join URL. Ensure the URL is correct and you have access to this meeting.',
        meeting: null,
        transcripts: [],
      };
    }

    span?.setAttribute('meeting_id', meeting.id);

    const transcripts = await this.listTranscripts(userProfileId, meeting.id);
    if (transcripts.length === 0) {
      return {
        success: true,
        message: 'Meeting found but no transcripts are available for this meeting.',
        meeting: toMeetingSummary(meeting),
        transcripts: [],
      };
    }

    span?.setAttribute('transcript_count', transcripts.length);

    // TODO: Use MCP elicitation to let the user pick which transcript when multiple exist
    const results = await this.ingestTranscripts(userProfileId, meeting, transcripts);
    const ingestedCount = results.filter((r) => r.status === 'ingested').length;

    return {
      success: ingestedCount > 0,
      message: `Ingested ${ingestedCount} of ${results.length} transcript(s) for meeting "${meeting.subject ?? 'Untitled Meeting'}".`,
      meeting: toMeetingSummary(meeting),
      transcripts: results,
    };
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
    const meeting = collection.value.at(0) ?? null;

    if (!meeting) {
      this.logger.warn({ joinWebUrl }, 'No meeting found for the provided join URL');
    } else {
      this.logger.debug({ meetingId: meeting.id, subject: meeting.subject }, 'Found meeting');
    }

    return meeting;
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
      await this.transcriptCreatedService.fetchVttAndIngest(
        userProfileId,
        '/me',
        meeting,
        transcript,
      );

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
