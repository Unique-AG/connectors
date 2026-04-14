import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import type { UniqueConfigNamespaced } from '~/config';
import { UniqueContentService } from '~/unique/unique-content.service';
import { UniqueUserMappingService } from '~/unique/unique-user-mapping.service';
import { buildTranscriptFilter, parseTranscriptMetadata } from './transcript-tools.helpers';

const ListMeetingsInputSchema = z.object({
  dateFrom: z.iso
    .datetime()
    .optional()
    .describe(
      'List meetings on or after this datetime (ISO 8601, e.g., 2024-01-15T00:00:00.000Z). Matches the meeting start date.',
    ),
  dateTo: z.iso
    .datetime()
    .optional()
    .describe(
      'List meetings on or before this datetime (ISO 8601, e.g., 2024-01-31T23:59:59.999Z). Matches the meeting start date.',
    ),
  organizer: z
    .string()
    .optional()
    .describe('Filter by meeting organizer name or email (partial match)'),
  participant: z
    .string()
    .optional()
    .describe('Filter by participant name or email (partial match)'),
  subject: z.string().optional().describe('Filter by meeting subject (partial match)'),
  skip: z.number().int().min(0).default(0).describe('Number of results to skip (for pagination)'),
  take: z
    .number()
    .int()
    .min(1)
    .max(50)
    .default(20)
    .describe('Maximum number of meetings to return'),
});

const MeetingItemSchema = z.object({
  id: z.string().describe('Content ID — use this to reference the meeting in other tools'),
  title: z.string().describe('Meeting subject / title'),
  meetingDate: z.string().optional().describe('Meeting start date (ISO 8601)'),
  organizer: z.string().optional().describe('Name of the meeting organizer'),
  participants: z.array(z.string()).optional().describe('List of participant names'),
});

const ListMeetingsOutputSchema = z.object({
  meetings: z.array(MeetingItemSchema).describe('List of meetings matching the filters'),
  total: z.number().describe('Total number of matching meetings'),
});

@Injectable()
export class ListMeetingsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly contentService: UniqueContentService,
    private readonly userMapping: UniqueUserMappingService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'list_meetings',
    title: 'List Meeting Transcripts',
    description:
      "Browse and list meetings with transcripts without requiring a search query. Use this to discover meetings by date range, organizer, participant, or subject. Returns meeting metadata including title, date, organizer, and participants. Use find_transcripts to search within a specific meeting's content.",
    parameters: ListMeetingsInputSchema,
    outputSchema: ListMeetingsOutputSchema,
    annotations: {
      title: 'List Meeting Transcripts',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'list',
      'unique.app/system-prompt':
        'Use this tool to browse meetings by date, organizer, or participant without a search query. Returns meeting IDs that can be used with find_transcripts for deeper search.',
    },
  })
  @Span()
  public async listMeetings(
    input: z.infer<typeof ListMeetingsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof ListMeetingsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const scopeContext = await this.userMapping.resolve(userProfileId);

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('unique_user_id', scopeContext.userId);
    span?.setAttribute('filter.has_date_from', !!input.dateFrom);
    span?.setAttribute('filter.has_date_to', !!input.dateTo);
    span?.setAttribute('filter.has_organizer', !!input.organizer);
    span?.setAttribute('filter.has_participant', !!input.participant);
    span?.setAttribute('filter.has_subject', !!input.subject);
    span?.setAttribute('skip', input.skip);
    span?.setAttribute('take', input.take);

    this.logger.debug(
      {
        hasDateFrom: !!input.dateFrom,
        hasDateTo: !!input.dateTo,
        hasOrganizer: !!input.organizer,
        hasParticipant: !!input.participant,
        hasSubject: !!input.subject,
        skip: input.skip,
        take: input.take,
      },
      'Listing meeting transcripts',
    );

    const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });

    const result = await this.contentService.scopedFindByMetadata(
      buildTranscriptFilter(rootScopeId, input),
      scopeContext,
      { skip: input.skip, take: input.take },
    );

    const meetings = result.contents.map((item) => {
      const { meetingDate, organizer, participants } = parseTranscriptMetadata(
        item.metadata as Record<string, unknown> | null,
      );

      return {
        id: item.id,
        title: item.title ?? 'Untitled Meeting',
        meetingDate,
        organizer,
        participants,
      };
    });

    span?.setAttribute('result_count', meetings.length);
    span?.setAttribute('total', result.total);

    this.logger.debug(
      { resultCount: meetings.length, total: result.total },
      'Listed meeting transcripts',
    );

    return { meetings, total: result.total };
  }
}
