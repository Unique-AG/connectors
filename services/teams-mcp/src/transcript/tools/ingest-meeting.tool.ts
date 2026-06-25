import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { Span, TraceService } from 'nestjs-otel';
import { fromString, parseTypeId, typeid } from 'typeid-js';
import * as z from 'zod';
import { GraphClientFactory } from '~/msgraph/graph-client.factory';
import { collectAllPages, GRAPH_PAGE_SIZE } from '~/msgraph/graph-pagination';
import { MeetingCollection, Transcript } from '../transcript.dtos';
import { TranscriptCreatedService } from '../transcript-created.service';

const IngestMeetingInputSchema = z.object({
  joinUrl: z
    .url()
    .describe(
      'The Teams meeting join URL (joinWebUrl). You must be the organizer or an invited attendee of the meeting.',
    ),
  date: z.iso
    .date()
    .optional()
    .describe(
      'Optional day (YYYY-MM-DD, UTC) to pick a transcript when a recurring meeting has several.',
    ),
});

const IngestMeetingOutputSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  meeting: z
    .object({
      id: z.string(),
      subject: z.string(),
      joinUrl: z.string(),
    })
    .nullable(),
  queued: z.array(
    z.object({
      transcriptId: z.string(),
      createdDate: z.string(),
    }),
  ),
});

@Injectable()
export class IngestMeetingTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly traceService: TraceService,
    private readonly graphClientFactory: GraphClientFactory,
    private readonly transcriptCreated: TranscriptCreatedService,
  ) {}

  @Tool({
    name: 'ingest_meeting',
    title: 'Ingest Meeting Transcript',
    description:
      'Ingest the transcript of a specific Microsoft Teams meeting on demand, identified by its join URL. Use this to ingest a meeting that predates the knowledge base integration, or to re-pull a single occurrence. You must be the organizer or an invited attendee. When a recurring meeting has multiple transcripts, pass an explicit date or pick one interactively. Ingestion runs asynchronously; the tool returns once the transcript has been queued.',
    parameters: IngestMeetingInputSchema,
    outputSchema: IngestMeetingOutputSchema,
    annotations: {
      title: 'Ingest Meeting Transcript',
      readOnlyHint: false,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'download',
      'unique.app/system-prompt':
        'Ingests a specific Teams meeting transcript by its join URL. Ask the user for the meeting join URL if not provided. If the meeting has multiple transcripts and no date is given, the user will be prompted to choose; if their client cannot prompt, ask them to provide a date (YYYY-MM-DD).',
    },
  })
  @Span()
  public async ingestMeeting(
    input: z.infer<typeof IngestMeetingInputSchema>,
    context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof IngestMeetingOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('filter.has_date', !!input.date);

    const client = this.graphClientFactory.createClientForUser(userProfileId);

    // 1. Resolve the meeting by its join URL. Delegated lookup works for both the organizer and
    // invited attendees, so we use `/me/...` (the consumer re-auths the same way).
    // Escape single quotes by doubling them so a crafted URL cannot break out of the OData
    // string literal and inject filter predicates.
    const escapedJoinUrl = input.joinUrl.replace(/'/g, "''");
    const meetingResponse = await client
      .api('/me/onlineMeetings')
      .filter(`JoinWebUrl eq '${escapedJoinUrl}'`)
      .get();
    const meetings = await MeetingCollection.parseAsync(meetingResponse);
    const meeting = meetings.value[0];

    if (!meeting) {
      span?.addEvent('meeting_not_found');
      this.logger.debug({ userProfileId }, 'No meeting matched the provided join URL');
      return {
        success: false,
        message: 'Meeting not found, or you do not have access to it.',
        meeting: null,
        queued: [],
      };
    }

    span?.setAttribute('meeting_id', meeting.id);

    const meetingInfo = {
      id: meeting.id,
      subject: meeting.subject ?? '',
      joinUrl: meeting.joinWebUrl.href,
    };

    // 2. List the meeting's transcripts. A meeting rarely has more than a page
    // of transcripts, but page through them anyway for consistency with the
    // other Graph collections.
    const transcriptsResponse = await client
      .api(`/me/onlineMeetings/${meeting.id}/transcripts`)
      .top(GRAPH_PAGE_SIZE)
      .get();
    const { items } = await collectAllPages(client, transcriptsResponse, {
      label: 'ingestMeeting.transcripts',
    });
    const transcripts = z.array(Transcript).parse(items);

    span?.setAttribute('transcript_count', transcripts.length);

    if (transcripts.length === 0) {
      span?.addEvent('no_transcripts');
      return {
        success: false,
        message:
          'This meeting has no transcripts yet. It may not have been transcribed, or the transcript is still processing.',
        meeting: meetingInfo,
        queued: [],
      };
    }

    // 3. Optionally narrow by date (UTC day of the transcript creation time).
    let candidates = transcripts;
    if (input.date) {
      candidates = candidates.filter(
        (t) => t.createdDateTime.toISOString().slice(0, 10) === input.date,
      );

      if (candidates.length === 0) {
        const availableDates = [
          ...new Set(transcripts.map((t) => t.createdDateTime.toISOString().slice(0, 10))),
        ].sort();
        span?.addEvent('date_matched_nothing');
        return {
          success: false,
          message: `No transcript was found for ${input.date}. Available transcript dates: ${availableDates.join(', ')}.`,
          meeting: meetingInfo,
          queued: [],
        };
      }
    }

    // 4. Resolve the final selection. A single candidate is used directly; multiple candidates
    // require interactive disambiguation via elicitation.
    let selected: typeof candidates;
    if (candidates.length === 1) {
      selected = candidates;
    } else {
      const caps = context.mcpServer.server.getClientCapabilities();
      if (!caps?.elicitation) {
        span?.addEvent('elicitation_unsupported');
        return {
          success: false,
          message:
            'This meeting has multiple transcripts and your client does not support interactive selection; pass an explicit `date` (YYYY-MM-DD) to choose one.',
          meeting: meetingInfo,
          queued: [],
        };
      }

      const result = await context.mcpServer.server.elicitInput({
        mode: 'form',
        message: `This meeting has ${candidates.length} transcripts. Which do you want to ingest?`,
        requestedSchema: {
          type: 'object',
          properties: {
            transcript: {
              type: 'string',
              title: 'Transcript',
              enum: candidates.map((t) => t.id),
              enumNames: candidates.map(
                (t) => `${meetingInfo.subject || 'Meeting'} — ${t.createdDateTime.toISOString()}`,
              ),
            },
          },
          required: ['transcript'],
        },
      });

      if (result.action !== 'accept') {
        span?.addEvent('elicitation_cancelled', { action: result.action });
        return {
          success: false,
          message: 'Selection cancelled.',
          meeting: meetingInfo,
          queued: [],
        };
      }

      const chosenId = result.content?.transcript;
      const chosen = candidates.find((t) => t.id === chosenId);
      if (!chosen) {
        span?.addEvent('elicitation_invalid_selection');
        return {
          success: false,
          message: 'The selected transcript is no longer available.',
          meeting: meetingInfo,
          queued: [],
        };
      }
      selected = [chosen];
    }

    // 5. Enqueue an ingest event per selected transcript (async — the upload happens downstream).
    const userProfileTid = fromString(userProfileId, 'user_profile');
    const pid = parseTypeId(userProfileTid);
    const userProfileTypeid = typeid(pid.prefix, pid.suffix);

    for (const transcript of selected) {
      await this.transcriptCreated.enqueueIngestRequested({
        userProfileId: userProfileTypeid,
        meetingId: meeting.id,
        transcriptId: transcript.id,
      });
    }

    const queued = selected.map((t) => ({
      transcriptId: t.id,
      createdDate: t.createdDateTime.toISOString(),
    }));

    span?.setAttribute('queued_count', queued.length);
    this.logger.log(
      { userProfileId, meetingId: meeting.id, queuedCount: queued.length },
      'Queued meeting transcript(s) for on-demand ingestion',
    );

    return {
      success: true,
      message: `Queued ${queued.length} transcript(s) for ingestion. They will appear in the knowledge base shortly.`,
      meeting: meetingInfo,
      queued,
    };
  }
}
