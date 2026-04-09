import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import type { UniqueConfigNamespaced } from '~/config';
import { type MetadataFilter, UniqueQLOperator } from '~/unique/unique.dtos';
import { UniqueContentService } from '~/unique/unique-content.service';

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
  total: z.number().optional().describe('Total number of matching meetings'),
});

@Injectable()
export class ListMeetingsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly contentService: UniqueContentService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'list_meetings',
    title: 'List Meeting Transcripts',
    description:
      'Browse and list meetings with transcripts without requiring a search query. Use this to discover meetings by date range, organizer, participant, or subject. Returns meeting metadata including title, date, organizer, and participants. Use find_transcripts to search within a specific meeting\'s content.',
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
    _request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof ListMeetingsOutputSchema>> {
    const span = this.traceService.getSpan();
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
    const filter = this.buildFilter(rootScopeId, input);

    const result = await this.contentService.findByMetadata(filter, {
      skip: input.skip,
      take: input.take,
    });

    const meetings = result.contents.map((item) => {
      const metadata = item.metadata as Record<string, unknown> | null;
      const participantNames = metadata?.participant_names;
      const participants =
        typeof participantNames === 'string'
          ? participantNames
              .split(',')
              .map((p) => p.trim())
              .filter(Boolean)
          : undefined;

      return {
        id: item.id,
        title: item.title ?? 'Untitled Meeting',
        meetingDate: typeof metadata?.date === 'string' ? metadata.date : undefined,
        organizer: typeof metadata?.organizer_name === 'string' ? metadata.organizer_name : undefined,
        participants: participants?.length ? participants : undefined,
      };
    });

    span?.setAttribute('result_count', meetings.length);
    span?.setAttribute('total', result.total);

    this.logger.debug({ resultCount: meetings.length, total: result.total }, 'Listed meeting transcripts');

    return { meetings, total: result.total };
  }

  private buildFilter(
    rootScopeId: string,
    input: z.infer<typeof ListMeetingsInputSchema>,
  ): MetadataFilter {
    const conditions: MetadataFilter[] = [
      {
        path: ['folderIdPath'],
        operator: UniqueQLOperator.CONTAINS,
        value: `uniquepathid://${rootScopeId}`,
      },
      {
        path: ['mimeType'],
        operator: UniqueQLOperator.EQUALS,
        value: 'text/vtt',
      },
    ];

    if (input.subject) {
      conditions.push({
        path: ['title'],
        operator: UniqueQLOperator.CONTAINS,
        value: input.subject,
      });
    }

    if (input.dateFrom) {
      conditions.push({
        path: ['metadata', 'date'],
        operator: UniqueQLOperator.GREATER_THAN_OR_EQUAL,
        value: input.dateFrom,
      });
    }

    if (input.dateTo) {
      conditions.push({
        path: ['metadata', 'date'],
        operator: UniqueQLOperator.LESS_THAN_OR_EQUAL,
        value: input.dateTo,
      });
    }

    if (input.organizer) {
      conditions.push({
        or: [
          {
            path: ['metadata', 'organizer_name'],
            operator: UniqueQLOperator.CONTAINS,
            value: input.organizer,
          },
          {
            path: ['metadata', 'organizer_email'],
            operator: UniqueQLOperator.CONTAINS,
            value: input.organizer,
          },
        ],
      });
    }

    if (input.participant) {
      conditions.push({
        or: [
          {
            path: ['metadata', 'participant_names'],
            operator: UniqueQLOperator.CONTAINS,
            value: input.participant,
          },
          {
            path: ['metadata', 'participant_emails'],
            operator: UniqueQLOperator.CONTAINS,
            value: input.participant,
          },
        ],
      });
    }

    return { and: conditions };
  }
}
