/**
 * Semantic Search Emails Tool
 *
 * This tool provides AI-powered semantic search capabilities for emails stored in Qdrant vector database.
 * It converts natural language queries into embeddings and searches for conceptually similar emails,
 * handling multiple vector types per email (full, summary, chunks) and applying sophisticated reranking strategies.
 *
 * The tool returns a list of email IDs ranked by semantic similarity, which can then be used to fetch
 * the full email details from the database.
 */

import { type McpAuthenticatedRequest } from '@unique-ag/mcp-oauth';
import { type Context, Tool } from '@unique-ag/mcp-server-module';
import {
  Injectable,
  InternalServerErrorException,
  Logger,
  UnauthorizedException,
} from '@nestjs/common';
import { components } from '@qdrant/js-client-rest/dist/types/openapi/generated_schema';
import dayjs from 'dayjs';
import { MetricService, Span } from 'nestjs-otel';
import { serializeError } from 'serialize-error-cjs';
import * as z from 'zod';
import { LLMService } from '../../../llm/llm.service';
import { QdrantService } from '../../../qdrant/qdrant.service';
import { normalizeError } from '../../../utils/normalize-error';
import { OTEL_ATTRIBUTES } from '../../../utils/otel-attributes';

const SemanticSearchEmailsInputSchema = z.object({
  query: z.string().describe('Natural language query to search for relevant emails'),
  limit: z.number().min(1).max(100).default(20).describe('Maximum number of emails to return'),
  scoreThreshold: z
    .number()
    .min(0)
    .max(1)
    .optional()
    .describe('Minimum similarity score threshold (0-1) for results'),
  dateFrom: z
    .string()
    .optional()
    .describe('Optional filter for emails from this date (ISO format: YYYY-MM-DD)'),
  dateTo: z
    .string()
    .optional()
    .describe('Optional filter for emails until this date (ISO format: YYYY-MM-DD)'),
  rerankingStrategy: z
    .enum(['max_score', 'weighted', 'proximity'])
    .default('weighted')
    .describe('Strategy for combining scores from multiple vectors per email'),
});

interface SearchResult {
  emailId: string;
  points: Array<{
    id: string;
    score: number;
    pointType: 'full' | 'summary' | 'chunk';
    chunkIndex?: number;
  }>;
  aggregateScore: number;
  bestMatchType: string;
}

@Injectable()
export class SemanticSearchEmailsTool {
  private readonly logger = new Logger(this.constructor.name);
  private readonly collectionName = 'emails';
  private readonly semanticSearchCounter;
  private readonly semanticSearchFailureCounter;

  public constructor(
    private readonly qdrantService: QdrantService,
    private readonly llmService: LLMService,
    metricService: MetricService,
  ) {
    this.semanticSearchCounter = metricService.getCounter('semantic_search_total', {
      description: 'Total number of semantic email searches',
    });
    this.semanticSearchFailureCounter = metricService.getCounter('semantic_search_failures_total', {
      description: 'Total number of semantic search failures',
    });
  }

  @Tool({
    name: 'semantic_search_emails',
    title: 'Semantic Search Emails',
    description:
      'Search emails using AI-powered semantic understanding. Finds conceptually similar emails even if they don\'t contain exact keyword matches. Ideal for complex queries like "emails about project deadlines" or "messages discussing budget concerns".',
    parameters: SemanticSearchEmailsInputSchema,
    annotations: {
      title: 'Semantic Search Emails',
      readOnlyHint: true,
      destructiveHint: false,
      idempotentHint: true,
      openWorldHint: true,
    },
    _meta: {
      'unique.app/icon': 'brain',
      'unique.app/system-prompt':
        'Use this for natural language queries where you want to find emails based on meaning and context rather than exact keywords. The AI understands concepts, so queries like "frustrated customers", "meeting scheduling", or "project updates" work well. Returns email IDs ranked by semantic similarity.',
    },
  })
  @Span((options, _context, _request) => ({
    attributes: {
      [OTEL_ATTRIBUTES.SEARCH_QUERY]: options.query,
      [OTEL_ATTRIBUTES.OUTLOOK_LIMIT]: options.limit,
      'semantic_search.reranking_strategy': options.rerankingStrategy,
    },
  }))
  public async semanticSearchEmails(
    {
      query,
      limit,
      scoreThreshold,
      dateFrom,
      dateTo,
      rerankingStrategy,
    }: z.infer<typeof SemanticSearchEmailsInputSchema>,
    _context: Context,
    request: McpAuthenticatedRequest,
  ) {
    const userProfileId = request.user?.userProfileId;
    if (!userProfileId) throw new UnauthorizedException('User not authenticated');

    this.incrementSearchCounter();

    try {
      const queryEmbedding = await this.generateQueryEmbedding(query);

      const queryRequest = await this.buildQueryRequest(
        queryEmbedding,
        userProfileId,
        limit * 3, // Get more results initially for reranking
        scoreThreshold,
        dateFrom,
        dateTo,
      );

      this.logger.debug({
        msg: 'Building search request',
        queryRequest,
      });

      const queryResults = await this.qdrantService.client.query(this.collectionName, {
        ...queryRequest,
      });

      const rankedEmails = this.groupAndRerankResults(queryResults.points, rerankingStrategy);
      const topEmails = rankedEmails.slice(0, limit);

      this.logger.debug({
        msg: 'Semantic search completed',
        query,
        totalPoints: queryResults.points.length,
        uniqueEmails: rankedEmails.length,
        returnedEmails: topEmails.length,
      });

      return {
        emailIds: topEmails.map((result) => result.emailId),
        results: topEmails.map((result) => ({
          emailId: result.emailId,
          score: result.aggregateScore,
          bestMatch: result.bestMatchType,
          matchCount: result.points.length,
        })),
        query,
        totalMatches: rankedEmails.length,
        rerankingStrategy,
        message: `Found ${topEmails.length} semantically similar emails`,
      };
    } catch (error) {
      this.incrementSearchFailureCounter('query_processing_error');
      this.logger.error({
        msg: 'Failed to perform semantic search',
        query,
        error: serializeError(normalizeError(error)),
      });
      throw new InternalServerErrorException('Failed to perform semantic search', {
        cause: error,
      });
    }
  }

  private async generateQueryEmbedding(query: string): Promise<number[]> {
    try {
      const embeddings = await this.llmService.contextualizedEmbed([[query]], 'query', {
        generationName: 'semantic-search-query-embedding',
      });

      if (!embeddings[0]?.[0]) throw new Error('Failed to generate query embedding');

      return embeddings[0][0];
    } catch (error) {
      this.logger.error({
        msg: 'Failed to generate query embedding',
        query,
        error: serializeError(normalizeError(error)),
      });
      throw error;
    }
  }

  private async buildQueryRequest(
    queryVector: number[],
    userProfileId: string,
    limit: number,
    scoreThreshold?: number,
    dateFrom?: string,
    dateTo?: string,
  ): Promise<components['schemas']['QueryRequest']> {
    const mustConditions: components['schemas']['Condition'][] = [
      {
        key: 'user_profile_id',
        match: { value: userProfileId },
      },
    ];

    // Add date filters if provided
    if (dateFrom) {
      mustConditions.push({
        key: 'created_at',
        range: {
          gte: dayjs(dateFrom).unix(),
        },
      });
    }

    if (dateTo) {
      mustConditions.push({
        key: 'created_at',
        range: {
          lte: dayjs(dateTo).unix(),
        },
      });
    }

    const queryRequest: components['schemas']['QueryRequest'] = {
      query: queryVector,
      using: 'content',
      filter: {
        must: mustConditions,
      },
      limit,
      with_payload: true,
    };

    if (scoreThreshold !== undefined) queryRequest.score_threshold = scoreThreshold;

    return queryRequest;
  }

  private groupAndRerankResults(
    points: components['schemas']['ScoredPoint'][],
    strategy: 'max_score' | 'weighted' | 'proximity' = 'weighted',
  ): SearchResult[] {
    // Group points by emailId
    const emailGroups = new Map<string, components['schemas']['ScoredPoint'][]>();

    for (const point of points) {
      const emailId = point.payload?.email_id;
      if (!emailId || typeof emailId !== 'string') continue;

      if (!emailGroups.has(emailId)) emailGroups.set(emailId, []);
      const group = emailGroups.get(emailId);
      if (group) group.push(point);
    }

    // Calculate aggregate scores based on strategy
    const rankedEmails: SearchResult[] = Array.from(emailGroups.entries()).map(
      ([emailId, emailPoints]) => {
        const processedPoints = emailPoints.map((point) => ({
          id: point.id as string, // We know the id is a string.
          score: point.score,
          // biome-ignore lint/style/noNonNullAssertion: we know the payload is not null.
          pointType: point.payload!.point_type as 'full' | 'summary' | 'chunk',
          // biome-ignore lint/style/noNonNullAssertion: we know the chunk index is not null.
          chunkIndex: point.payload!.chunk_index as number | undefined,
        }));

        let aggregateScore: number;
        switch (strategy) {
          case 'max_score':
            aggregateScore = this.calculateMaxScore(processedPoints);
            break;
          case 'proximity':
            aggregateScore = this.calculateProximityScore(processedPoints);
            break;
          case 'weighted':
            aggregateScore = this.calculateWeightedScore(processedPoints);
            break;
        }

        const bestMatchType = this.getBestMatchType(processedPoints);

        return {
          emailId,
          points: processedPoints,
          aggregateScore,
          bestMatchType,
        };
      },
    );

    return rankedEmails.sort((a, b) => b.aggregateScore - a.aggregateScore);
  }

  private calculateMaxScore(points: Array<{ score: number; pointType: string }>): number {
    return Math.max(...points.map((p) => p.score));
  }

  private calculateWeightedScore(points: Array<{ score: number; pointType: string }>): number {
    const weights = {
      full: 1.2,
      summary: 1.0,
      chunk: 0.8,
    };

    let maxWeightedScore = 0;
    for (const point of points) {
      const weight = weights[point.pointType as keyof typeof weights] || 1.0;
      const weightedScore = point.score * weight;
      maxWeightedScore = Math.max(maxWeightedScore, weightedScore);
    }

    return maxWeightedScore;
  }

  private calculateProximityScore(
    points: Array<{ score: number; pointType: string; chunkIndex?: number }>,
  ): number {
    const chunks = points
      .filter((p) => p.pointType === 'chunk' && p.chunkIndex !== undefined)
      .sort((a, b) => (a.chunkIndex || 0) - (b.chunkIndex || 0));

    let proximityBonus = 0;

    // Check for consecutive chunks
    for (let i = 0; i < chunks.length - 1; i++) {
      const currentChunk = chunks[i];
      const nextChunk = chunks[i + 1];
      if (currentChunk && nextChunk) {
        const currentChunkIndex = currentChunk.chunkIndex ?? 0;
        const nextChunkIndex = nextChunk.chunkIndex ?? 0;
        if (currentChunkIndex + 1 === nextChunkIndex) {
          proximityBonus += 0.1; // Boost for consecutive matches
        }
      }
    }

    // Get base weighted score
    const baseScore = this.calculateWeightedScore(points);

    return baseScore + proximityBonus;
  }

  private getBestMatchType(
    points: Array<{ score: number; pointType: 'full' | 'summary' | 'chunk' }>,
  ): 'full' | 'summary' | 'chunk' | 'unknown' {
    const sortedByScore = [...points].sort((a, b) => b.score - a.score);
    return sortedByScore[0]?.pointType || 'unknown';
  }

  private incrementSearchCounter() {
    if (this.semanticSearchCounter) this.semanticSearchCounter.add(1);
  }

  private incrementSearchFailureCounter(reason: string) {
    if (this.semanticSearchFailureCounter) this.semanticSearchFailureCounter.add(1, { reason });
  }
}
