import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import { Injectable, Logger, UnauthorizedException } from '@nestjs/common';
import { ConfigService } from '@nestjs/config';
import { Span, TraceService } from 'nestjs-otel';
import * as z from 'zod';
import type { UniqueConfigNamespaced } from '~/config';
import { type MetadataFilter, UniqueQLOperator } from '~/unique/unique.dtos';
import { UniqueContentService } from '~/unique/unique-content.service';

/**
 * Typed interface for transcript metadata stored during ingestion.
 * The generic metadata schema uses `unknown` for values, but we know the specific
 * types for our transcript metadata fields.
 */
interface TranscriptMetadata {
  date?: string;
  participant_names?: string;
  participant_emails?: string;
  participant_user_profile_ids?: string;
  content_correlation_id?: string;
}

const FindTranscriptsInputSchema = z.object({
  subject: z.string().optional().describe('Filter by meeting subject (partial match)'),
  dateFrom: z
    .string()
    .datetime()
    .optional()
    .describe('Filter transcripts from this datetime (ISO 8601, e.g., 2024-01-15T00:00:00.000Z)'),
  dateTo: z
    .string()
    .datetime()
    .optional()
    .describe('Filter transcripts until this datetime (ISO 8601, e.g., 2024-01-31T23:59:59.999Z)'),
  participant: z
    .string()
    .optional()
    .describe('Filter by participant name or email (partial match)'),
  skip: z.number().int().min(0).default(0).describe('Number of results to skip for pagination'),
  take: z
    .number()
    .int()
    .min(1)
    .max(100)
    .default(20)
    .describe('Maximum number of results to return'),
});

const TranscriptItemSchema = z.object({
  id: z.string(),
  title: z.string().nullable(),
  date: z.string().nullable(),
  participantNames: z.string().nullable(),
  participantEmails: z.string().nullable(),
  readUrl: z.string().nullable(),
});

const FindTranscriptsOutputSchema = z.object({
  transcripts: z.array(TranscriptItemSchema),
  total: z.number(),
  message: z.string(),
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
    title: 'Find Meeting Transcripts',
    description:
      'Search for meeting transcripts in the knowledge base. Filter by subject, date range, or participant. Returns transcript metadata including title, date, and participants.',
    parameters: FindTranscriptsInputSchema,
    outputSchema: FindTranscriptsOutputSchema,
    annotations: {
      title: 'Find Meeting Transcripts',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: false,
    },
    _meta: {
      'unique.app/icon': 'search',
      'unique.app/system-prompt':
        'Use this tool to search for meeting transcripts that were previously ingested in knowledge base. You can filter by subject, date range, or participant name/email. All filters are optional and can be combined.',
    },
  })
  @Span()
  public async findTranscripts(
    input: z.infer<typeof FindTranscriptsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    const span = this.traceService.getSpan();
    span?.setAttribute('user_profile_id', userProfileId);
    span?.setAttribute('filter.has_subject', !!input.subject);
    span?.setAttribute('filter.has_date_from', !!input.dateFrom);
    span?.setAttribute('filter.has_date_to', !!input.dateTo);
    span?.setAttribute('filter.has_participant', !!input.participant);

    this.logger.debug(
      {
        userProfileId,
        hasSubject: !!input.subject,
        hasDateFrom: !!input.dateFrom,
        hasDateTo: !!input.dateTo,
        hasParticipant: !!input.participant,
        skip: input.skip,
        take: input.take,
      },
      'Searching for meeting transcripts',
    );

    const rootScopePath = this.config.get('unique.rootScopePath', { infer: true });
    const filter = this.buildMetadataFilter(rootScopePath, userProfileId, input);
    this.logger.debug({ filter }, 'metadata filter');

    const result = await this.contentService.findByMetadata(filter, {
      skip: input.skip,
      take: input.take,
    });

    const transcripts = result.contents.map((content) => {
      // Cast to our known transcript metadata structure
      const metadata = content.metadata as TranscriptMetadata | null | undefined;
      return {
        id: content.id,
        title: content.title,
        date: metadata?.date ?? null,
        participantNames: metadata?.participant_names ?? null,
        participantEmails: metadata?.participant_emails ?? null,
        readUrl: content.readUrl ?? null,
      };
    });

    span?.setAttribute('result_count', transcripts.length);

    this.logger.debug(
      { userProfileId, resultCount: transcripts.length },
      'Successfully retrieved meeting transcripts',
    );

    return {
      transcripts,
      total: result.total,
      message:
        result.total > 0
          ? `Found ${result.total} transcript(s) matching your criteria.`
          : 'No transcripts found matching your criteria.',
    };
  }

  private buildMetadataFilter(
    rootScopePath: string,
    userProfileId: string,
    input: z.infer<typeof FindTranscriptsInputSchema>,
  ): MetadataFilter {
    const conditions: MetadataFilter[] = [
      {
        path: ['folderIdPath'],
        operator: UniqueQLOperator.CONTAINS,
        value: `uniquepathid://${rootScopePath}`,
      },
      // Permission filter: only return transcripts where the current user is a participant
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

    return { and: conditions };
  }
}
