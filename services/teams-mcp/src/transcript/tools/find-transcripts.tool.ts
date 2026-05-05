import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import type { UniqueConfigNamespaced } from '~/config';
import { type PublicSearchRequest, SearchType } from '~/unique/unique.dtos';
import { UniqueContentService } from '~/unique/unique-content.service';
import { UniqueUserMappingService } from '~/unique/unique-user-mapping.service';
import { buildTranscriptFilter, parseTranscriptMetadata } from './transcript-tools.helpers';

const FindTranscriptsInputSchema = z.object({
  query: z.string().describe('Search query to find relevant content within transcripts'),
  subject: z.string().optional().describe('Filter by meeting subject (partial match)'),
  dateFrom: z.iso
    .datetime()
    .optional()
    .describe(
      'Filter transcripts from this datetime (ISO 8601, e.g., 2024-01-15T00:00:00.000Z). Matches the meeting start date.',
    ),
  dateTo: z.iso
    .datetime()
    .optional()
    .describe(
      'Filter transcripts until this datetime (ISO 8601, e.g., 2024-01-31T23:59:59.999Z). Matches the meeting start date.',
    ),
  organizer: z
    .string()
    .optional()
    .describe('Filter by meeting organizer name or email (partial match)'),
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
});

const TranscriptChunkSchema = z.object({
  id: z.string().describe('Unique content ID'),
  chunkId: z.string().optional().describe('Chunk ID within the content'),
  title: z.string().describe('Meeting title'),
  key: z.string().optional().describe('Content key/filename'),
  text: z.string().describe('The relevant passage'),
  url: z.string().optional().describe('External URL if applicable'),
  meetingDate: z.string().optional().describe('Date of the meeting'),
  startDatetime: z.string().optional().describe('Meeting start datetime (ISO 8601)'),
  endDatetime: z.string().optional().describe('Meeting end datetime (ISO 8601)'),
  organizer: z.string().optional().describe('Name of the meeting organizer'),
  participants: z.array(z.string()).optional().describe('List of participants'),
});

const FindTranscriptsOutputSchema = z.object({
  results: z
    .array(TranscriptChunkSchema)
    .describe('Search results. Use [N] to cite result at index N (e.g., [0], [1])'),
});

@Injectable()
export class FindTranscriptsTool {
  private readonly logger = new Logger(this.constructor.name);

  public constructor(
    private readonly config: ConfigService<UniqueConfigNamespaced, true>,
    private readonly contentService: UniqueContentService,
    private readonly userMapping: UniqueUserMappingService,
    private readonly traceService: TraceService,
  ) {}

  @Tool({
    name: 'find_transcripts',
    title: 'Search Meeting Transcripts',
    description:
      'Search for content within meeting transcripts using hybrid semantic + keyword search. Supports filtering by date range (dateFrom/dateTo), meeting organizer, participant, and subject. Returns relevant passages that can be cited using [N] notation where N is the result index.',
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
        'Use this tool to search meeting transcripts. Cite results using [N] where N is the array index (e.g., [0] for first result, [1] for second). The platform will automatically convert these to proper references.',
    },
  })
  @Span()
  public async findTranscripts(
    input: z.infer<typeof FindTranscriptsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ): Promise<z.output<typeof FindTranscriptsOutputSchema>> {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) {
      throw new UnauthorizedException('User not authenticated');
    }

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('query_length', input.query.length);
    span?.setAttribute('filter.has_subject', !!input.subject);
    span?.setAttribute('filter.has_date_from', !!input.dateFrom);
    span?.setAttribute('filter.has_date_to', !!input.dateTo);
    span?.setAttribute('filter.has_organizer', !!input.organizer);
    span?.setAttribute('filter.has_participant', !!input.participant);

    const scopeContext = await this.userMapping.resolve(userProfileId);
    span?.setAttribute('unique_user_id', scopeContext.userId);

    this.logger.debug(
      {
        userProfileId,
        uniqueUserId: scopeContext.userId,
        queryLength: input.query.length,
        hasSubject: !!input.subject,
        hasDateFrom: !!input.dateFrom,
        hasDateTo: !!input.dateTo,
        hasOrganizer: !!input.organizer,
        hasParticipant: !!input.participant,
        limit: input.limit,
      },
      'Searching within meeting transcripts',
    );

    const rootScopeId = this.config.get('unique.rootScopeId', { infer: true });
    const searchRequest = this.buildSearchRequest(rootScopeId, input);

    const result = await this.contentService.scopedSearch(searchRequest, scopeContext);

    const results = result.data.map((item) => {
      const { meetingDate, startDatetime, endDatetime, organizer, participants } =
        parseTranscriptMetadata(item.metadata as Record<string, unknown> | null);

      return {
        id: item.id,
        chunkId: item.chunkId,
        title: item.title ?? 'Untitled Transcript',
        key: item.key,
        text: item.text,
        url: `unique://content/${item.id}`,
        meetingDate,
        startDatetime,
        endDatetime,
        organizer,
        participants,
      };
    });

    span?.setAttribute('result_count', results.length);

    this.logger.debug(
      { userProfileId, resultCount: results.length },
      'Successfully searched meeting transcripts',
    );

    return { results };
  }

  private buildSearchRequest(
    rootScopeId: string,
    input: z.infer<typeof FindTranscriptsInputSchema>,
  ): PublicSearchRequest {
    return {
      searchString: input.query,
      searchType: SearchType.COMBINED,
      limit: input.limit,
      scoreThreshold: 0,
      metaDataFilter: buildTranscriptFilter(rootScopeId, input),
    };
  }
}
