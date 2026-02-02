import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { MeetingCollection, TranscriptCollection } from '../transcript.dtos';
import { TranscriptCreatedService } from '../transcript-created.service';

const GetMeetingTranscriptInputSchema = z.object({
  joinWebUrl: z.string().url().describe('The Microsoft Teams meeting join URL'),
});

const IngestedTranscriptSchema = z.object({
  id: z.string(),
  createdDateTime: z.string(),
  endDateTime: z.string(),
  status: z.enum(['ingested', 'failed']),
  error: z.string().optional(),
});

const GetMeetingTranscriptOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  meeting: z
    .object({
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
    })
    .nullable(),
  transcripts: z.array(IngestedTranscriptSchema),
});

@Injectable()
export class GetMeetingTranscriptTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly graphClientFactory: GraphClientFactory,
    private readonly transcriptCreatedService: TranscriptCreatedService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'get_meeting_transcript',
    title: 'Get Meeting Transcript',
    description:
      'Given a Microsoft Teams meeting link (joinWebUrl), fetches all transcripts for that meeting and ingests them into the knowledge base.',
    parameters: GetMeetingTranscriptInputSchema,
    outputSchema: GetMeetingTranscriptOutputSchema,
    annotations: {
      title: 'Get Meeting Transcript',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'transcript',
      'unique.app/system-prompt':
        'Fetches and ingests transcripts for a specific Teams meeting identified by its join URL. Use this when a user provides a Teams meeting link and wants the transcript ingested into the knowledge base.',
    },
  })
  @Span()
  public async getMeetingTranscript(
    input: z.infer<typeof GetMeetingTranscriptInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('join_web_url', input.joinWebUrl);

    this.logger.debug(
      { userProfileId, joinWebUrl: input.joinWebUrl },
      'Looking up meeting by join URL',
    );

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    // Step 1: Find the meeting by joinWebUrl
    const meetingResponse = await client
      .api('/me/onlineMeetings')
      .filter(`JoinWebUrl eq '${input.joinWebUrl}'`)
      .get();

    const meetingCollection = await MeetingCollection.parseAsync(meetingResponse);
    const meeting = meetingCollection.value.at(0);

    if (!meeting) {
      this.logger.warn(
        { joinWebUrl: input.joinWebUrl },
        'No meeting found for the provided join URL',
      );
      return {
        success: false,
        message:
          'No meeting found for the provided join URL. Ensure the URL is correct and you have access to this meeting.',
        meeting: null,
        transcripts: [],
      };
    }

    span?.setAttribute('meeting_id', meeting.id);
    this.logger.debug({ meetingId: meeting.id, subject: meeting.subject }, 'Found meeting');

    // Step 2: List transcripts for the meeting
    const transcriptResponse = await client
      .api(`/me/onlineMeetings/${meeting.id}/transcripts`)
      .get();

    const transcriptCollection = await TranscriptCollection.parseAsync(transcriptResponse);

    const meetingSummary = {
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

    if (transcriptCollection.value.length === 0) {
      this.logger.debug({ meetingId: meeting.id }, 'No transcripts found for meeting');
      return {
        success: true,
        message: 'Meeting found but no transcripts are available for this meeting.',
        meeting: meetingSummary,
        transcripts: [],
      };
    }

    span?.setAttribute('transcript_count', transcriptCollection.value.length);
    this.logger.debug(
      { meetingId: meeting.id, transcriptCount: transcriptCollection.value.length },
      'Found transcripts for meeting',
    );

    // Step 3: Fetch VTT content and ingest each transcript
    // TODO: Use MCP elicitation to let the user pick which transcript when multiple exist
    const results: z.infer<typeof IngestedTranscriptSchema>[] = [];

    for (const transcript of transcriptCollection.value) {
      try {
        await this.transcriptCreatedService.fetchVttAndIngest(client, '/me', meeting, transcript);

        results.push({
          id: transcript.id,
          createdDateTime: transcript.createdDateTime.toISOString(),
          endDateTime: transcript.endDateTime.toISOString(),
          status: 'ingested',
        });

        this.logger.log(
          { transcriptId: transcript.id, meetingId: meeting.id },
          'Successfully ingested transcript',
        );
      } catch (error) {
        const errorMessage = error instanceof Error ? error.message : String(error);
        this.logger.error(
          { transcriptId: transcript.id, meetingId: meeting.id, error: errorMessage },
          'Failed to ingest transcript',
        );
        results.push({
          id: transcript.id,
          createdDateTime: transcript.createdDateTime.toISOString(),
          endDateTime: transcript.endDateTime.toISOString(),
          status: 'failed',
          error: errorMessage,
        });
      }
    }

    const ingestedCount = results.filter((r) => r.status === 'ingested').length;

    return {
      success: ingestedCount > 0,
      message: `Ingested ${ingestedCount} of ${results.length} transcript(s) for meeting "${meeting.subject ?? 'Untitled Meeting'}".`,
      meeting: meetingSummary,
      transcripts: results,
    };
  }
}
