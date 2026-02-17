import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import type { UniqueConfigNamespaced } from '~/config';
import {
  type MetadataFilter,
  type PublicSearchRequest,
  SearchType,
  UniqueQLOperator,
} from '~/unique/unique.dtos';
import { UniqueContentService } from '~/unique/unique-content.service';

const FindTranscriptsInputSchema = z.object({
  query: z.string().describe('Search query to find relevant content within transcripts'),
  subject: z.string().optional().describe('Filter by meeting subject (partial match)'),
  dateFrom: z
    .iso
    .datetime()
    .optional()
    .describe('Filter transcripts from this datetime (ISO 8601, e.g., 2024-01-15T00:00:00.000Z)'),
  dateTo: z
    .iso
    .datetime()
    .optional()
    .describe('Filter transcripts until this datetime (ISO 8601, e.g., 2024-01-31T23:59:59.999Z)'),
  participant: z
    .string()
    .optional()
    .describe('Filter by participant name or email (partial match)'),
  limit: z
    .number()
    .int()
    .min(1)
    .max(100)
    .default(10)
    .describe('Maximum number of results to return'),
  scoreThreshold: z
    .number()
    .min(0)
    .max(1)
    .optional()
    .describe('Minimum relevance score threshold (0-1)'),
});

const TranscriptResultSchema = z.object({
  id: z.string().describe('Unique identifier for this transcript chunk'),
  title: z.string().describe('Meeting title or transcript name'),
  text: z.string().describe('The relevant passage/excerpt'),
  url: z.string().describe('URL to the source content'),
  sequenceNumber: z.number().describe('Citation number [1], [2], etc.'),
  meetingDate: z.string().optional().describe('Date of the meeting'),
  participants: z.array(z.string()).optional().describe('List of participants'),
});

const FindTranscriptsOutputSchema = z.object({
  summary: z.string().describe('Summary of findings with [N] citation markers'),
  results: z.array(TranscriptResultSchema),
  totalCount: z.number().optional().describe('Total number of results'),
});

@Injectable()
export class FindTranscriptsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly contentService: UniqueContentService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'find_transcripts',
    title: 'Search Meeting Transcripts',
    description:
      'Search for content within meeting transcripts using semantic search. Provide a search query to find relevant passages. Optionally filter by subject, date range, or participant.',
    parameters: FindTranscriptsInputSchema,
    outputSchema: FindTranscriptsOutputSchema,
    annotations: {
      title: 'Search Meeting Transcripts',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'search',
      'unique.app/system-prompt':
        'Use this tool to search within meeting transcripts using semantic search. Provide a search query to find relevant passages. You can optionally filter by subject, date range, or participant name/email.',
    },
  })
  @Span()
  public async findTranscripts(
    input: z.infer<typeof FindTranscriptsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof FindTranscriptsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('query_length', input.query.length);
    span?.setAttribute('filter.has_subject', !!input.subject);
    span?.setAttribute('filter.has_date_from', !!input.dateFrom);
    span?.setAttribute('filter.has_date_to', !!input.dateTo);
    span?.setAttribute('filter.has_participant', !!input.participant);

    this.logger.debug(
      {
        userProfileId,
        queryLength: input.query.length,
        hasSubject: !!input.subject,
        hasDateFrom: !!input.dateFrom,
        hasDateTo: !!input.dateTo,
        hasParticipant: !!input.participant,
        limit: input.limit,
      },
      'Searching within meeting transcripts',
    );

    const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });
    const searchRequest = this.buildSearchRequest(rootScopeId, userProfileId, input);

    const result = await this.contentService.search(searchRequest);

    const results = result.data.map((item, index) => {
      const metadata = item.metadata as Record<string, unknown> | null;
      const participantNames = metadata?.participant_names;
      const participants =
        typeof participantNames === 'string'
          ? participantNames.split(',').map((p) => p.trim()).filter(Boolean)
          : undefined;

      return {
        id: item.chunkId,
        title: item.title ?? 'Untitled Transcript',
        text: item.text,
        url: `unique://content/${item.id}`,
        sequenceNumber: index + 1,
        meetingDate: typeof metadata?.date === 'string' ? metadata.date : undefined,
        participants: participants?.length ? participants : undefined,
      };
    });

    span?.setAttribute('result_count', results.length);

    this.logger.debug(
      { userProfileId, resultCount: results.length },
      'Successfully searched meeting transcripts',
    );

    const summary =
      results.length > 0
        ? `Found ${results.length} relevant passage(s) in transcripts:\n\n` +
          results
            .map((r) => `[${r.sequenceNumber}] ${r.title}: "${r.text.slice(0, 150)}${r.text.length > 150 ? '...' : ''}"`)
            .join('\n\n')
        : 'No relevant content found in transcripts matching your query.';

    return {
      summary,
      results,
      totalCount: results.length,
    };
  }

  private buildSearchRequest(
    rootScopeId: string,
    userProfileId: string,
    input: z.infer<typeof FindTranscriptsInputSchema>,
  ): PublicSearchRequest {
    const conditions: MetadataFilter[] = [
      // Scope filter: only return content under our root scope
      {
        path: ['folderIdPath'],
        operator: UniqueQLOperator.CONTAINS,
        value: `uniquepathid://${rootScopeId}`,
      },
      // Type filter: only return transcripts (VTT files), not recordings
      {
        path: ['mimeType'],
        operator: UniqueQLOperator.EQUALS,
        value: 'text/vtt',
      },
      // REVIEW: Is this actually needed given how ACL works in KB and through the public API?
      // NOTE: Permission filter: only return transcripts where the current user is a participant.
      // Uses CONTAINS on comma-separated IDs which is safe in practice since user profile IDs
      // are UUIDs - the probability of a partial match across ID boundaries is negligible.
      {
        path: ['metadata', 'participant_user_profile_ids'],
        operator: UniqueQLOperator.CONTAINS,
        value: userProfileId,
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

    return {
      searchString: input.query,
      searchType: SearchType.VECTOR,
      limit: input.limit,
      scoreThreshold: input.scoreThreshold,
      metaDataFilter: { and: conditions },
    };
  }
}
